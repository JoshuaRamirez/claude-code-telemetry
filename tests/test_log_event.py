"""Tests for log_event() dispatcher.

Target: hooks/db_logger.py:643-775

Strategy: Patch all sub-functions at module level, verify dispatch logic.
"""

import pytest
from unittest.mock import patch, MagicMock, ANY
from datetime import datetime

from hooks.db_logger import log_event


pytestmark = pytest.mark.unit


# Shared patch targets
_P = 'hooks.db_logger.'


@pytest.fixture
def mock_all():
    """Patch all sub-functions used by log_event. Returns dict of mocks."""
    patches = {}
    targets = [
        'get_connection',
        'get_or_create_session',
        'log_hook_event',
        'log_tool_invocation',
        'update_tool_invocation',
        'log_user_prompt',
        'log_stop_event',
        'log_subagent_event',
        'log_compact_event',
        'log_notification_event',
        'update_session_metadata',
        'close_session',
        'get_git_info',
        'capture_git_changes',
        'capture_git_changes_incremental',
        'parse_transcript',
        'parse_transcript_incremental',
        'log_messages',
        'log_token_usage',
    ]
    stack = {}
    patchers = []
    for t in targets:
        p = patch(_P + t)
        mock = p.start()
        stack[t] = mock
        patchers.append(p)

    # Default return values for happy path
    mock_conn = MagicMock()
    stack['get_connection'].return_value = mock_conn
    stack['get_or_create_session'].return_value = '1'
    stack['log_hook_event'].return_value = 100
    stack['get_git_info'].return_value = ('main', 'abc123')
    stack['parse_transcript_incremental'].return_value = []
    stack['parse_transcript'].return_value = []

    yield stack

    for p in patchers:
        p.stop()


# ---------------------------------------------------------------------------
# Failure modes (short-circuits)
# ---------------------------------------------------------------------------

class TestLogEventFailures:
    def test_connection_failure(self, mock_all):
        mock_all['get_connection'].return_value = None
        result = log_event('PreToolUse', {})
        assert result == {}
        mock_all['get_or_create_session'].assert_not_called()

    def test_session_failure(self, mock_all):
        mock_all['get_or_create_session'].return_value = None
        result = log_event('PreToolUse', {})
        assert result == {}
        mock_all['log_hook_event'].assert_not_called()

    def test_event_id_failure(self, mock_all):
        mock_all['log_hook_event'].return_value = None
        result = log_event('PreToolUse', {})
        assert result == {}
        mock_all['log_tool_invocation'].assert_not_called()


# ---------------------------------------------------------------------------
# PreToolUse
# ---------------------------------------------------------------------------

class TestLogEventPreToolUse:
    def test_logs_tool_invocation(self, mock_all):
        data = {'tool_name': 'Read', 'tool_input': {'file_path': '/test.py'},
                'tool_use_id': 'tu-1'}
        result = log_event('PreToolUse', data)
        assert result == {}
        mock_all['log_tool_invocation'].assert_called_once()
        args = mock_all['log_tool_invocation'].call_args
        assert args[0][2] == 'Read'  # tool_name
        assert args[1]['tool_use_id'] == 'tu-1'


# ---------------------------------------------------------------------------
# PostToolUse
# ---------------------------------------------------------------------------

class TestLogEventPostToolUse:
    def test_updates_tool_invocation(self, mock_all):
        data = {'tool_name': 'Read', 'tool_use_id': 'tu-1',
                'tool_response': 'file contents'}
        log_event('PostToolUse', data)
        mock_all['update_tool_invocation'].assert_called_once()

    def test_write_tool_triggers_git_capture(self, mock_all):
        data = {'tool_name': 'Write', 'tool_use_id': 'tu-1',
                'tool_input': {'file_path': '/app.py'}}
        log_event('PostToolUse', data)
        mock_all['capture_git_changes_incremental'].assert_called_once()

    def test_edit_tool_triggers_git_capture(self, mock_all):
        data = {'tool_name': 'Edit', 'tool_use_id': 'tu-1',
                'tool_input': {'file_path': '/app.py'}}
        log_event('PostToolUse', data)
        mock_all['capture_git_changes_incremental'].assert_called_once()

    def test_non_write_tool_no_git_capture(self, mock_all):
        data = {'tool_name': 'Read', 'tool_use_id': 'tu-1'}
        log_event('PostToolUse', data)
        mock_all['capture_git_changes_incremental'].assert_not_called()

    def test_transcript_parsing(self, mock_all):
        mock_all['parse_transcript_incremental'].return_value = [
            {'uuid': 'm1', 'role': 'user', 'content': 'test'}
        ]
        data = {'tool_name': 'Read', 'transcript_path': '/t.jsonl'}
        log_event('PostToolUse', data)
        mock_all['log_messages'].assert_called_once()
        mock_all['log_token_usage'].assert_called_once()

    def test_tool_response_dict_serialized(self, mock_all):
        """Non-string tool_response gets JSON-serialized."""
        data = {'tool_name': 'Read', 'tool_use_id': 'tu-1',
                'tool_response': {'status': 'ok', 'data': [1, 2, 3]}}
        log_event('PostToolUse', data)
        call_args = mock_all['update_tool_invocation'].call_args
        # update_tool_invocation(conn, tool_use_id, tool_result, completed_at)
        tool_result = call_args[0][2]
        assert '"status"' in tool_result  # JSON-serialized


# ---------------------------------------------------------------------------
# UserPromptSubmit
# ---------------------------------------------------------------------------

class TestLogEventUserPromptSubmit:
    def test_logs_prompt(self, mock_all):
        data = {'prompt': 'Hello Claude'}
        log_event('UserPromptSubmit', data)
        mock_all['log_user_prompt'].assert_called_once_with(ANY, 100, 'Hello Claude')


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------

class TestLogEventStop:
    def test_logs_stop_and_closes(self, mock_all):
        data = {'reason': 'end_turn', 'transcript_path': '/t.jsonl'}
        log_event('Stop', data)
        mock_all['log_stop_event'].assert_called_once()
        mock_all['parse_transcript'].assert_called_once()
        mock_all['capture_git_changes'].assert_called_once()
        mock_all['close_session'].assert_called_once()


# ---------------------------------------------------------------------------
# SessionStart
# ---------------------------------------------------------------------------

class TestLogEventSessionStart:
    def test_updates_metadata(self, mock_all):
        data = {'model': 'claude-sonnet'}
        log_event('SessionStart', data)
        mock_all['get_git_info'].assert_called_once()
        mock_all['update_session_metadata'].assert_called_once_with(
            ANY, '1', 'claude-sonnet', 'main', 'abc123')


# ---------------------------------------------------------------------------
# SubagentStop
# ---------------------------------------------------------------------------

class TestLogEventSubagentStop:
    def test_logs_subagent(self, mock_all):
        data = {'agent_type': 'code-review', 'task_description': 'Review PR',
                'result': 'LGTM'}
        log_event('SubagentStop', data)
        mock_all['log_subagent_event'].assert_called_once()

    def test_result_dict_serialized(self, mock_all):
        data = {'agent_type': 'test', 'result': {'score': 95}}
        log_event('SubagentStop', data)
        args = mock_all['log_subagent_event'].call_args
        # log_subagent_event(conn, event_id, agent_type, task_description, result)
        result_arg = args[0][4]
        assert '"score"' in result_arg


# ---------------------------------------------------------------------------
# PreCompact
# ---------------------------------------------------------------------------

class TestLogEventPreCompact:
    def test_logs_compact(self, mock_all):
        data = {'summary_content': 'compressed'}
        log_event('PreCompact', data)
        mock_all['log_compact_event'].assert_called_once()

    def test_summary_dict_serialized(self, mock_all):
        data = {'summary_content': {'key': 'val'}}
        log_event('PreCompact', data)
        args = mock_all['log_compact_event'].call_args
        # log_compact_event(conn, event_id, summary_content)
        assert '"key"' in args[0][2]


# ---------------------------------------------------------------------------
# Notification
# ---------------------------------------------------------------------------

class TestLogEventNotification:
    def test_logs_notification(self, mock_all):
        data = {'notification_type': 'info', 'notification_content': 'Hello'}
        log_event('Notification', data)
        mock_all['log_notification_event'].assert_called_once()

    def test_content_dict_serialized(self, mock_all):
        data = {'notification_type': 'warn', 'notification_content': {'detail': 1}}
        log_event('Notification', data)
        args = mock_all['log_notification_event'].call_args
        # log_notification_event(conn, event_id, notification_type, notification_content)
        assert '"detail"' in args[0][3]
