"""Tests for complex DB functions combining DB + file I/O + subprocess.

Target: hooks/db_logger.py -- parse_transcript_incremental, log_token_usage,
        log_messages, capture_git_changes, capture_git_changes_incremental
"""

import json
from unittest.mock import patch

import pyodbc
import pytest

from hooks.db_logger import (
    capture_git_changes,
    capture_git_changes_incremental,
    log_messages,
    log_token_usage,
    parse_transcript_incremental,
)
from tests.conftest import make_subprocess_result

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# parse_transcript_incremental()
# ---------------------------------------------------------------------------

class TestParseTranscriptIncremental:
    def test_from_start(self, mock_conn, mock_cursor, tmp_path):
        """First call with position=0 reads everything."""
        mock_cursor.fetchone.return_value = (0,)  # LastTranscriptPosition = 0
        f = tmp_path / "t.jsonl"
        f.write_text(json.dumps({'type': 'user', 'message': {'content': 'hi'}}) + "\n")

        result = parse_transcript_incremental(mock_conn, '1', str(f))
        assert len(result) == 1
        assert result[0]['role'] == 'user'

    def test_from_midpoint(self, mock_conn, mock_cursor, tmp_path):
        """Resumes from saved position, only parses new lines."""
        line1 = json.dumps({'type': 'user', 'message': {'content': 'old'}}) + "\n"
        line2 = json.dumps({'type': 'user', 'message': {'content': 'new'}}) + "\n"
        f = tmp_path / "t.jsonl"
        f.write_text(line1 + line2)

        # Position after first line
        mock_cursor.fetchone.return_value = (len(line1.encode('utf-8')),)
        result = parse_transcript_incremental(mock_conn, '1', str(f))
        assert len(result) == 1
        assert result[0]['content'] == 'new'

    def test_updates_position(self, mock_conn, mock_cursor, tmp_path):
        """Verifies position is saved back to DB after parsing."""
        mock_cursor.fetchone.return_value = (0,)
        f = tmp_path / "t.jsonl"
        content = json.dumps({'type': 'user', 'message': {'content': 'hi'}}) + "\n"
        f.write_text(content)

        parse_transcript_incremental(mock_conn, '1', str(f))
        # Should have UPDATE Sessions SET LastTranscriptPosition
        update_calls = [c for c in mock_cursor.execute.call_args_list
                        if 'UPDATE' in str(c) and 'LastTranscriptPosition' in str(c)]
        assert len(update_calls) == 1

    def test_empty_file(self, mock_conn, mock_cursor, tmp_path):
        mock_cursor.fetchone.return_value = (0,)
        f = tmp_path / "empty.jsonl"
        f.write_text("")
        result = parse_transcript_incremental(mock_conn, '1', str(f))
        assert result == []

    def test_file_not_found(self, mock_conn, mock_cursor):
        mock_cursor.fetchone.return_value = (0,)
        result = parse_transcript_incremental(mock_conn, '1', '/nonexistent.jsonl')
        assert result == []

    def test_skips_invalid_json(self, mock_conn, mock_cursor, tmp_path):
        mock_cursor.fetchone.return_value = (0,)
        f = tmp_path / "bad.jsonl"
        f.write_text("NOT JSON\n" + json.dumps({'type': 'user', 'message': {'content': 'ok'}}) + "\n")
        result = parse_transcript_incremental(mock_conn, '1', str(f))
        assert len(result) == 1


# ---------------------------------------------------------------------------
# log_token_usage()
# ---------------------------------------------------------------------------

class TestLogTokenUsage:
    def test_no_usage_data(self, mock_conn, mock_cursor):
        """Messages without usage are skipped."""
        msgs = [{'role': 'user', 'content': 'hi'}]
        log_token_usage(mock_conn, '1', msgs)
        # Only commit, no INSERT
        assert mock_cursor.execute.call_count == 0
        mock_conn.commit.assert_called_once()

    def test_new_record_inserted(self, mock_conn, mock_cursor):
        """Token usage is inserted directly (dedup handled by unique index + IntegrityError)."""
        msgs = [{
            'uuid': 'msg-1',
            'model': 'claude-sonnet-4-20250514',
            'usage': {
                'input_tokens': 100,
                'output_tokens': 50,
                'cache_creation_tokens': 5,
                'cache_read_tokens': 10,
                'service_tier': 'standard',
            }
        }]
        log_token_usage(mock_conn, '1', msgs)
        # Direct INSERT (unique index + try/except IntegrityError handles dedup)
        insert_calls = [c for c in mock_cursor.execute.call_args_list
                        if 'INSERT' in str(c)]
        assert len(insert_calls) == 1

    def test_duplicate_handled_by_integrity_error(self, mock_conn, mock_cursor):
        """Duplicate INSERT raises IntegrityError, caught and skipped."""
        mock_cursor.execute.side_effect = pyodbc.IntegrityError('23000', 'dup key')
        msgs = [{'uuid': 'existing-uuid', 'model': 'test',
                 'usage': {'input_tokens': 10, 'output_tokens': 5}}]
        # Should not raise — IntegrityError caught internally
        log_token_usage(mock_conn, '1', msgs)
        mock_conn.rollback.assert_called_once()  # Defensive rollback
        mock_conn.commit.assert_called_once()

    def test_no_uuid_still_inserts(self, mock_conn, mock_cursor):
        """Messages without uuid still insert (NULL excluded from unique index)."""
        msgs = [{'model': 'test',
                 'usage': {'input_tokens': 10, 'output_tokens': 5}}]
        log_token_usage(mock_conn, '1', msgs)
        insert_calls = [c for c in mock_cursor.execute.call_args_list
                        if 'INSERT' in str(c)]
        assert len(insert_calls) == 1

    def test_cost_calculation(self, mock_conn, mock_cursor):
        """Verify cost is computed and passed to INSERT."""
        msgs = [{'uuid': 'msg-cost', 'model': 'claude-sonnet-4-20250514',
                 'usage': {'input_tokens': 1_000_000, 'output_tokens': 1_000_000}}]
        mock_cursor.fetchone.return_value = None  # Not existing
        log_token_usage(mock_conn, '1', msgs)
        insert_calls = [c for c in mock_cursor.execute.call_args_list
                        if 'INSERT' in str(c)]
        assert len(insert_calls) == 1
        # Cost param is last in the VALUES tuple
        params = insert_calls[0][0][1]
        cost = params[-1]
        # Sonnet: 3.0 + 15.0 = 18.0
        assert abs(cost - 18.0) < 0.01

    def test_multiple_messages(self, mock_conn, mock_cursor):
        msgs = [
            {'uuid': 'm1', 'model': 'test',
             'usage': {'input_tokens': 10, 'output_tokens': 5}},
            {'uuid': 'm2', 'model': 'test',
             'usage': {'input_tokens': 20, 'output_tokens': 10}},
        ]
        mock_cursor.fetchone.return_value = None
        log_token_usage(mock_conn, '1', msgs)
        insert_calls = [c for c in mock_cursor.execute.call_args_list
                        if 'INSERT' in str(c)]
        assert len(insert_calls) == 2


# ---------------------------------------------------------------------------
# log_messages()
# ---------------------------------------------------------------------------

class TestLogMessages:
    def test_basic_insert(self, mock_conn, mock_cursor):
        msgs = [{'uuid': 'u1', 'parent_uuid': 'p1', 'role': 'user',
                 'content': 'hi', 'model': None, 'timestamp': None,
                 'thinking_content': None}]
        log_messages(mock_conn, '1', msgs)
        assert mock_cursor.execute.call_count == 1
        mock_conn.commit.assert_called_once()

    def test_duplicate_handled_by_integrity_error(self, mock_conn, mock_cursor):
        """Duplicate INSERT raises IntegrityError, caught and skipped."""
        mock_cursor.execute.side_effect = pyodbc.IntegrityError('23000', 'dup key')
        msgs = [{'uuid': 'existing', 'role': 'user', 'content': 'dup'}]
        # Should not raise — IntegrityError caught internally
        log_messages(mock_conn, '1', msgs)
        mock_conn.rollback.assert_called_once()  # Defensive rollback
        mock_conn.commit.assert_called_once()

    def test_dedup_always_active(self, mock_conn, mock_cursor):
        """Dedup is always active via unique index + IntegrityError (no flag needed)."""
        msgs = [{'uuid': 'new-uuid', 'role': 'assistant', 'content': 'yes'}]
        log_messages(mock_conn, '1', msgs)
        insert_calls = [c for c in mock_cursor.execute.call_args_list
                        if 'INSERT' in str(c)]
        assert len(insert_calls) == 1

    def test_timestamp_z_strip(self, mock_conn, mock_cursor):
        """Timestamps ending with Z have it stripped and T replaced."""
        msgs = [{'uuid': 'ts1', 'role': 'user', 'content': 'test',
                 'timestamp': '2026-01-15T14:30:00.123456Z'}]
        log_messages(mock_conn, '1', msgs)
        insert_call = mock_cursor.execute.call_args_list[0]
        params = insert_call[0][1]
        ts = params[6]  # Timestamp is 7th param (0-indexed)
        assert 'Z' not in ts
        assert 'T' not in ts
        assert '2026-01-15 14:30:00.123456' == ts

    def test_timestamp_truncation(self, mock_conn, mock_cursor):
        """Timestamps with fractional seconds longer than 6 digits are truncated."""
        msgs = [{'uuid': 'ts2', 'role': 'user', 'content': 'test',
                 'timestamp': '2026-01-15T14:30:00.12345678901234'}]
        log_messages(mock_conn, '1', msgs)
        insert_call = mock_cursor.execute.call_args_list[0]
        params = insert_call[0][1]
        ts = params[6]
        # Should be truncated to max 26 chars total
        assert len(ts) <= 26

    def test_trigger_event_id(self, mock_conn, mock_cursor):
        """TriggerEventId is passed through to the INSERT."""
        msgs = [{'uuid': 'te1', 'role': 'user', 'content': 'test'}]
        log_messages(mock_conn, '1', msgs, trigger_event_id=42)
        insert_call = mock_cursor.execute.call_args_list[0]
        params = insert_call[0][1]
        # TriggerEventId is second-to-last param (ContentBlocksJson is last)
        assert params[-2] == 42

    def test_content_blocks_json_stored(self, mock_conn, mock_cursor):
        """ContentBlocksJson is passed through to the INSERT."""
        cbj = '[{"type": "text", "text": "hello"}]'
        msgs = [{'uuid': 'cbj1', 'role': 'assistant', 'content': 'hello',
                 'content_blocks_json': cbj}]
        log_messages(mock_conn, '1', msgs)
        insert_call = mock_cursor.execute.call_args_list[0]
        params = insert_call[0][1]
        assert params[-1] == cbj  # ContentBlocksJson is last param


# ---------------------------------------------------------------------------
# capture_git_changes()
# ---------------------------------------------------------------------------

class TestCaptureGitChanges:
    @patch('hooks.db_logger.subprocess.run')
    def test_uses_merge_sql(self, mock_run, mock_conn, mock_cursor):
        """Full capture uses MERGE (upsert) to prevent duplicates from Stop+SessionEnd."""
        mock_run.return_value = make_subprocess_result(
            stdout="10\t0\tfile.py\n")
        capture_git_changes(mock_conn, '1')
        sql = mock_cursor.execute.call_args[0][0]
        assert 'MERGE' in sql

    @patch('hooks.db_logger.subprocess.run')
    def test_added_file(self, mock_run, mock_conn, mock_cursor):
        mock_run.return_value = make_subprocess_result(
            stdout="10\t0\tfile.py\n")
        capture_git_changes(mock_conn, '1')
        params = mock_cursor.execute.call_args[0][1]
        # MERGE params: (session, filepath, change, added, deleted, session, filepath, change, added, deleted)
        assert params[2] == 'added'  # ChangeType (WHEN MATCHED UPDATE)
        assert params[3] == 10  # LinesAdded
        assert params[4] == 0   # LinesDeleted
        assert params[7] == 'added'  # ChangeType (WHEN NOT MATCHED INSERT)

    @patch('hooks.db_logger.subprocess.run')
    def test_deleted_file(self, mock_run, mock_conn, mock_cursor):
        mock_run.return_value = make_subprocess_result(
            stdout="0\t15\told.py\n")
        capture_git_changes(mock_conn, '1')
        params = mock_cursor.execute.call_args[0][1]
        assert params[2] == 'deleted'

    @patch('hooks.db_logger.subprocess.run')
    def test_modified_file(self, mock_run, mock_conn, mock_cursor):
        mock_run.return_value = make_subprocess_result(
            stdout="5\t3\tapp.py\n")
        capture_git_changes(mock_conn, '1')
        params = mock_cursor.execute.call_args[0][1]
        assert params[2] == 'modified'

    @patch('hooks.db_logger.subprocess.run')
    def test_binary_dashes(self, mock_run, mock_conn, mock_cursor):
        """Binary files show '-' for added/deleted counts."""
        mock_run.return_value = make_subprocess_result(
            stdout="-\t-\timage.png\n")
        capture_git_changes(mock_conn, '1')
        params = mock_cursor.execute.call_args[0][1]
        assert params[3] == 0  # LinesAdded (binary dash -> 0)
        assert params[4] == 0  # LinesDeleted (binary dash -> 0)
        assert params[2] == 'modified'  # both 0 -> modified

    @patch('hooks.db_logger.subprocess.run')
    def test_empty_lines_skipped(self, mock_run, mock_conn, mock_cursor):
        """Empty lines between data lines in git output are skipped."""
        mock_run.return_value = make_subprocess_result(
            stdout="5\t3\tapp.py\n\n2\t0\tnew.py\n")
        capture_git_changes(mock_conn, '1')
        assert mock_cursor.execute.call_count == 2  # 2 files, empty line skipped

    @patch('hooks.db_logger.subprocess.run')
    def test_git_failure(self, mock_run, mock_conn, mock_cursor):
        mock_run.return_value = make_subprocess_result(returncode=1)
        capture_git_changes(mock_conn, '1')
        mock_cursor.execute.assert_not_called()

    @patch('hooks.db_logger.subprocess.run', side_effect=Exception("boom"))
    def test_exception(self, mock_run, mock_conn, mock_cursor):
        capture_git_changes(mock_conn, '1')
        mock_cursor.execute.assert_not_called()


# ---------------------------------------------------------------------------
# capture_git_changes_incremental()
# ---------------------------------------------------------------------------

class TestCaptureGitChangesIncremental:
    @patch('hooks.db_logger.subprocess.run')
    def test_no_filepath(self, mock_run, mock_conn, mock_cursor):
        mock_run.return_value = make_subprocess_result(stdout="3\t1\tfile.py\n")
        capture_git_changes_incremental(mock_conn, '1')
        cmd = mock_run.call_args[0][0]
        assert '--' not in cmd

    @patch('hooks.db_logger.subprocess.run')
    def test_with_filepath(self, mock_run, mock_conn, mock_cursor):
        mock_run.return_value = make_subprocess_result(stdout="3\t1\tfile.py\n")
        capture_git_changes_incremental(mock_conn, '1', filepath='file.py')
        cmd = mock_run.call_args[0][0]
        assert '--' in cmd
        assert 'file.py' in cmd

    @patch('hooks.db_logger.subprocess.run')
    def test_merge_sql(self, mock_run, mock_conn, mock_cursor):
        """Incremental capture uses MERGE (upsert) instead of INSERT."""
        mock_run.return_value = make_subprocess_result(stdout="5\t2\tapp.py\n")
        capture_git_changes_incremental(mock_conn, '1')
        sql = mock_cursor.execute.call_args[0][0]
        assert 'MERGE' in sql

    @patch('hooks.db_logger.subprocess.run')
    def test_added_file(self, mock_run, mock_conn, mock_cursor):
        """Incremental: file with only additions classified as 'added'."""
        mock_run.return_value = make_subprocess_result(stdout="8\t0\tnew.py\n")
        capture_git_changes_incremental(mock_conn, '1')
        params = mock_cursor.execute.call_args[0][1]
        assert params[2] == 'added'

    @patch('hooks.db_logger.subprocess.run')
    def test_deleted_file(self, mock_run, mock_conn, mock_cursor):
        """Incremental: file with only deletions classified as 'deleted'."""
        mock_run.return_value = make_subprocess_result(stdout="0\t12\told.py\n")
        capture_git_changes_incremental(mock_conn, '1')
        params = mock_cursor.execute.call_args[0][1]
        assert params[2] == 'deleted'

    @patch('hooks.db_logger.subprocess.run')
    def test_empty_lines_skipped(self, mock_run, mock_conn, mock_cursor):
        """Empty lines between data lines in git output are skipped."""
        mock_run.return_value = make_subprocess_result(
            stdout="3\t1\tfile.py\n\n1\t0\tother.py\n")
        capture_git_changes_incremental(mock_conn, '1')
        assert mock_cursor.execute.call_count == 2  # 2 files, empty line skipped

    @patch('hooks.db_logger.subprocess.run', side_effect=Exception("git error"))
    def test_exception(self, mock_run, mock_conn, mock_cursor):
        capture_git_changes_incremental(mock_conn, '1')
        mock_cursor.execute.assert_not_called()

    @patch('hooks.db_logger.subprocess.run')
    def test_git_nonzero_return(self, mock_run, mock_conn, mock_cursor):
        mock_run.return_value = make_subprocess_result(returncode=128)
        capture_git_changes_incremental(mock_conn, '1')
        mock_cursor.execute.assert_not_called()
