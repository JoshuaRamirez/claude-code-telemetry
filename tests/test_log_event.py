"""Tests for log_event() dispatcher.

Target: hooks/db_logger.py — log_event()

v2.1 changes tested:
- Stop no longer calls close_session (moved to SessionEnd)
- SessionEnd handler: final parse + git capture + close_session
- SubagentStop captures tool_use_id
- UserPromptSubmit handles both 'prompt' and 'user_prompt' fields
"""

from unittest.mock import ANY, MagicMock, patch

import pytest

from hooks.db_logger import log_event

pytestmark = pytest.mark.unit


# Shared patch targets
_P = 'hooks.db_logger.'


@pytest.fixture
def mock_all():
    """Patch all sub-functions used by log_event. Returns dict of mocks."""
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
        tool_result = call_args[0][2]
        assert '"status"' in tool_result


# ---------------------------------------------------------------------------
# UserPromptSubmit
# ---------------------------------------------------------------------------

class TestLogEventUserPromptSubmit:
    def test_logs_prompt(self, mock_all):
        data = {'prompt': 'Hello Claude'}
        log_event('UserPromptSubmit', data)
        mock_all['log_user_prompt'].assert_called_once_with(ANY, 100, 'Hello Claude')

    def test_user_prompt_field_fallback(self, mock_all):
        """Falls back to 'user_prompt' when 'prompt' is not present."""
        data = {'user_prompt': 'Hello via user_prompt'}
        log_event('UserPromptSubmit', data)
        mock_all['log_user_prompt'].assert_called_once_with(ANY, 100, 'Hello via user_prompt')

    def test_empty_prompt_defaults(self, mock_all):
        """Missing both 'prompt' and 'user_prompt' defaults to empty string."""
        data = {}
        log_event('UserPromptSubmit', data)
        mock_all['log_user_prompt'].assert_called_once_with(ANY, 100, '')

    def test_transcript_parsing(self, mock_all):
        """UserPromptSubmit with transcript parses incrementally."""
        mock_all['parse_transcript_incremental'].return_value = [
            {'uuid': 'm1', 'role': 'user', 'content': 'hello'}
        ]
        data = {'prompt': 'test', 'transcript_path': '/t.jsonl'}
        log_event('UserPromptSubmit', data)
        mock_all['parse_transcript_incremental'].assert_called_once()
        mock_all['log_messages'].assert_called_once()
        mock_all['log_token_usage'].assert_called_once()


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------

class TestLogEventStop:
    def test_logs_stop_without_close(self, mock_all):
        """Stop logs event and parses transcript but does NOT close session."""
        data = {'reason': 'end_turn', 'transcript_path': '/t.jsonl'}
        log_event('Stop', data)
        mock_all['log_stop_event'].assert_called_once()
        mock_all['parse_transcript'].assert_called_once()
        mock_all['capture_git_changes'].assert_called_once()
        # Session is NOT closed by Stop anymore (moved to SessionEnd)
        mock_all['close_session'].assert_not_called()

    def test_stop_with_messages_logs_and_tokens(self, mock_all):
        """Stop with parsed messages calls log_messages and log_token_usage."""
        mock_all['parse_transcript'].return_value = [
            {'uuid': 'm1', 'role': 'user', 'content': 'test',
             'usage': {'input_tokens': 50}}
        ]
        data = {'reason': 'end_turn', 'transcript_path': '/t.jsonl'}
        log_event('Stop', data)
        mock_all['log_messages'].assert_called_once()
        mock_all['log_token_usage'].assert_called_once()


# ---------------------------------------------------------------------------
# SessionEnd (new)
# ---------------------------------------------------------------------------

class TestLogEventSessionEnd:
    def test_session_end_full_parse_and_close(self, mock_all):
        """SessionEnd does final parse, git capture, and closes session."""
        data = {'transcript_path': '/t.jsonl'}
        log_event('SessionEnd', data)
        mock_all['parse_transcript'].assert_called_once_with('/t.jsonl')
        mock_all['capture_git_changes'].assert_called_once()
        mock_all['close_session'].assert_called_once()

    def test_session_end_no_transcript(self, mock_all):
        """SessionEnd without transcript path still closes session."""
        data = {}
        log_event('SessionEnd', data)
        mock_all['parse_transcript'].assert_not_called()
        mock_all['close_session'].assert_called_once()

    def test_session_end_with_messages(self, mock_all):
        """SessionEnd with messages logs them and token usage."""
        mock_all['parse_transcript'].return_value = [
            {'uuid': 'm1', 'role': 'assistant', 'content': 'final answer',
             'usage': {'input_tokens': 100}}
        ]
        data = {'transcript_path': '/t.jsonl'}
        log_event('SessionEnd', data)
        mock_all['log_messages'].assert_called_once()
        mock_all['log_token_usage'].assert_called_once()


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
        result_arg = args[0][4]
        assert '"score"' in result_arg

    def test_tool_use_id_passed(self, mock_all):
        """SubagentStop passes tool_use_id to log_subagent_event."""
        data = {'agent_type': 'test', 'result': 'ok', 'tool_use_id': 'tu-42'}
        log_event('SubagentStop', data)
        args = mock_all['log_subagent_event'].call_args
        assert args[1]['tool_use_id'] == 'tu-42'

    def test_no_tool_use_id(self, mock_all):
        """SubagentStop without tool_use_id passes None."""
        data = {'agent_type': 'test', 'result': 'ok'}
        log_event('SubagentStop', data)
        args = mock_all['log_subagent_event'].call_args
        assert args[1]['tool_use_id'] is None


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
        assert '"key"' in args[0][2]


# ---------------------------------------------------------------------------
# Notification
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestLogEventErrorHandling:
    def test_unexpected_exception_returns_empty(self, mock_all):
        """Unexpected exception in log_event is caught and returns {}."""
        mock_all['log_hook_event'].side_effect = RuntimeError("unexpected crash")
        result = log_event('PreToolUse', {})
        assert result == {}


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
        assert '"detail"' in args[0][3]
