"""Tests for simple DB functions that follow cursor/execute/fetchone/commit pattern.

Target: hooks/db_logger.py -- 12 functions
All use mock_conn/mock_cursor fixtures from conftest.
"""

import json
import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime

from hooks.db_logger import (
    get_connection,
    get_or_create_session,
    log_hook_event,
    log_tool_invocation,
    log_user_prompt,
    log_stop_event,
    log_subagent_event,
    log_compact_event,
    log_notification_event,
    update_session_metadata,
    close_session,
    update_tool_invocation,
)


pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# get_connection()
# ---------------------------------------------------------------------------

class TestGetConnection:
    @patch('hooks.db_logger.pyodbc')
    def test_success(self, mock_pyodbc):
        mock_pyodbc.connect.return_value = MagicMock()
        conn = get_connection()
        assert conn is not None
        mock_pyodbc.connect.assert_called_once()

    @patch('hooks.db_logger.pyodbc')
    def test_failure_returns_none(self, mock_pyodbc):
        mock_pyodbc.connect.side_effect = Exception("connection failed")
        conn = get_connection()
        assert conn is None


# ---------------------------------------------------------------------------
# get_or_create_session()
# ---------------------------------------------------------------------------

class TestGetOrCreateSession:
    def test_existing_session_found(self, mock_conn, mock_cursor):
        mock_cursor.fetchone.return_value = (42,)
        result = get_or_create_session(mock_conn, claude_session_id='sid-123')
        assert result == '42'
        # Should SELECT first, not INSERT
        sql = mock_cursor.execute.call_args_list[0][0][0]
        assert 'SELECT' in sql

    def test_no_claude_id_creates_new(self, mock_conn, mock_cursor):
        mock_cursor.fetchone.return_value = (99,)
        result = get_or_create_session(mock_conn, working_dir='/test')
        assert result == '99'
        # With no claude_session_id, skips SELECT, goes straight to INSERT
        sql = mock_cursor.execute.call_args_list[0][0][0]
        assert 'INSERT' in sql

    def test_new_created_when_no_existing(self, mock_conn, mock_cursor):
        # First fetchone (SELECT) returns None, second fetchone (INSERT) returns new id
        mock_cursor.fetchone.side_effect = [None, (77,)]
        result = get_or_create_session(mock_conn, claude_session_id='sid-new')
        assert result == '77'

    def test_no_row_returned(self, mock_conn, mock_cursor):
        mock_cursor.fetchone.return_value = None
        result = get_or_create_session(mock_conn)
        assert result is None


# ---------------------------------------------------------------------------
# log_hook_event()
# ---------------------------------------------------------------------------

class TestLogHookEvent:
    def test_success(self, mock_conn, mock_cursor):
        mock_cursor.fetchone.return_value = (101,)
        result = log_hook_event(mock_conn, '1', 'PreToolUse', '{"test": 1}',
                                claude_session_id='s1', transcript_path='/t.jsonl',
                                cwd='/cwd', permission_mode='default')
        assert result == 101
        mock_conn.commit.assert_called_once()

    def test_no_row(self, mock_conn, mock_cursor):
        mock_cursor.fetchone.return_value = None
        result = log_hook_event(mock_conn, '1', 'PreToolUse', '{}')
        assert result is None


# ---------------------------------------------------------------------------
# log_tool_invocation()
# ---------------------------------------------------------------------------

class TestLogToolInvocation:
    def test_success(self, mock_conn, mock_cursor):
        mock_cursor.fetchone.return_value = (200,)
        result = log_tool_invocation(mock_conn, 1, 'Read',
                                      {'file_path': '/test.py'})
        assert result == 200

    def test_json_serialization(self, mock_conn, mock_cursor):
        tool_input = {'command': 'ls', 'timeout': 5000}
        mock_cursor.fetchone.return_value = (201,)
        log_tool_invocation(mock_conn, 1, 'Bash', tool_input)
        # Verify the JSON was serialized in the execute call
        calls = mock_cursor.execute.call_args_list
        # The INSERT call is the second execute (after BEGIN TRANSACTION)
        insert_call = calls[1]
        params = insert_call[0][1]
        assert params[-1] == json.dumps(tool_input)  # ToolInputJson is last param

    def test_none_input(self, mock_conn, mock_cursor):
        mock_cursor.fetchone.return_value = (202,)
        log_tool_invocation(mock_conn, 1, 'Read', None)
        calls = mock_cursor.execute.call_args_list
        insert_call = calls[1]
        params = insert_call[0][1]
        assert params[-1] is None  # ToolInputJson should be None

    def test_exception_triggers_rollback(self, mock_conn, mock_cursor):
        mock_cursor.execute.side_effect = [
            None,  # BEGIN TRANSACTION
            Exception("SQL error"),  # INSERT fails
            None,  # ROLLBACK
        ]
        result = log_tool_invocation(mock_conn, 1, 'Bash', {})
        assert result is None
        # Verify ROLLBACK was called (third execute call)
        rollback_call = mock_cursor.execute.call_args_list[2]
        assert 'ROLLBACK' in rollback_call[0][0]


# ---------------------------------------------------------------------------
# log_user_prompt()
# ---------------------------------------------------------------------------

class TestLogUserPrompt:
    def test_success(self, mock_conn, mock_cursor):
        mock_cursor.fetchone.return_value = (300,)
        result = log_user_prompt(mock_conn, 1, 'Hello Claude')
        assert result == 300
        mock_conn.commit.assert_called_once()

    def test_no_row(self, mock_conn, mock_cursor):
        mock_cursor.fetchone.return_value = None
        result = log_user_prompt(mock_conn, 1, 'test')
        assert result is None


# ---------------------------------------------------------------------------
# log_stop_event()
# ---------------------------------------------------------------------------

class TestLogStopEvent:
    def test_success(self, mock_conn, mock_cursor):
        mock_cursor.fetchone.return_value = (400,)
        result = log_stop_event(mock_conn, 1, 'end_turn')
        assert result == 400
        mock_conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# log_subagent_event()
# ---------------------------------------------------------------------------

class TestLogSubagentEvent:
    def test_success(self, mock_conn, mock_cursor):
        mock_cursor.fetchone.return_value = (500,)
        result = log_subagent_event(mock_conn, 1, 'code-review',
                                     task_description='Review PR',
                                     result='approved')
        assert result == 500
        mock_conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# log_compact_event()
# ---------------------------------------------------------------------------

class TestLogCompactEvent:
    def test_success(self, mock_conn, mock_cursor):
        mock_cursor.fetchone.return_value = (600,)
        result = log_compact_event(mock_conn, 1, summary_content='compressed context')
        assert result == 600
        mock_conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# log_notification_event()
# ---------------------------------------------------------------------------

class TestLogNotificationEvent:
    def test_success(self, mock_conn, mock_cursor):
        mock_cursor.fetchone.return_value = (700,)
        result = log_notification_event(mock_conn, 1,
                                         notification_type='info',
                                         notification_content='message')
        assert result == 700
        mock_conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# update_session_metadata()
# ---------------------------------------------------------------------------

class TestUpdateSessionMetadata:
    def test_verify_sql_params(self, mock_conn, mock_cursor):
        update_session_metadata(mock_conn, '42',
                                 model='claude-sonnet', git_branch='main',
                                 git_commit='abc123')
        mock_cursor.execute.assert_called_once()
        params = mock_cursor.execute.call_args[0][1]
        assert params == ('claude-sonnet', 'main', 'abc123', '42')
        mock_conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# close_session()
# ---------------------------------------------------------------------------

class TestCloseSession:
    def test_verify_sql_called(self, mock_conn, mock_cursor):
        close_session(mock_conn, '42')
        mock_cursor.execute.assert_called_once()
        sql = mock_cursor.execute.call_args[0][0]
        assert 'UPDATE Sessions' in sql
        assert 'EndedAt' in sql
        mock_conn.commit.assert_called_once()


# ---------------------------------------------------------------------------
# update_tool_invocation()
# ---------------------------------------------------------------------------

class TestUpdateToolInvocation:
    def test_no_tool_use_id(self, mock_conn):
        result = update_tool_invocation(mock_conn, None)
        assert result is False

    def test_no_matching_record(self, mock_conn, mock_cursor):
        mock_cursor.fetchone.return_value = None
        result = update_tool_invocation(mock_conn, 'tu-123')
        assert result is False

    def test_success_with_duration(self, mock_conn, mock_cursor):
        started = datetime(2026, 1, 1, 12, 0, 0)
        completed = datetime(2026, 1, 1, 12, 0, 1, 500000)  # 1.5 seconds later

        mock_cursor.fetchone.return_value = (started,)
        mock_cursor.rowcount = 1

        result = update_tool_invocation(mock_conn, 'tu-123',
                                         tool_result='ok', completed_at=completed)
        assert result is True
        mock_conn.commit.assert_called_once()
        # Verify duration_ms was calculated
        update_call = mock_cursor.execute.call_args_list[-1]
        params = update_call[0][1]
        assert params[2] == 1500  # duration_ms

    def test_already_completed_returns_false(self, mock_conn, mock_cursor):
        """If row[0] is None (StartedAt is NULL or already completed), return False."""
        mock_cursor.fetchone.return_value = (None,)
        result = update_tool_invocation(mock_conn, 'tu-123')
        assert result is False
