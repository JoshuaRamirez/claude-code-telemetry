"""Tests for hook entry point main() functions.

Target: hooks/db_*.py (8 files)

All 7 standard hooks follow the identical pattern:
  stdin -> json.load -> log_event -> json.dumps -> stdout -> sys.exit(0)

db_sessionstart.py adds health check gating.
"""

import json
import sys
from io import StringIO
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Standard hooks (identical pattern)
# ---------------------------------------------------------------------------

STANDARD_HOOKS = [
    ('hooks.db_pretooluse', 'PreToolUse'),
    ('hooks.db_posttooluse', 'PostToolUse'),
    ('hooks.db_stop', 'Stop'),
    ('hooks.db_userpromptsubmit', 'UserPromptSubmit'),
    ('hooks.db_subagentstop', 'SubagentStop'),
    ('hooks.db_precompact', 'PreCompact'),
    ('hooks.db_notification', 'Notification'),
    ('hooks.db_sessionend', 'SessionEnd'),
]


class TestStandardHooks:
    @pytest.mark.parametrize("module_path,event_type", STANDARD_HOOKS)
    def test_happy_path(self, module_path, event_type):
        """Standard hook reads stdin, calls log_event, writes stdout, exits 0."""
        import importlib
        mod = importlib.import_module(module_path)

        input_data = {'tool_name': 'Read', 'session_id': 's1'}
        mock_stdin = StringIO(json.dumps(input_data))

        with patch.object(sys, 'stdin', mock_stdin), \
             patch(f'{module_path}.log_event', return_value={'allowed': True}) as mock_log, \
             patch('sys.stdout', new_callable=StringIO) as mock_stdout:

            with pytest.raises(SystemExit) as exc_info:
                mod.main()

            assert exc_info.value.code == 0
            mock_log.assert_called_once_with(event_type, input_data)
            output = json.loads(mock_stdout.getvalue())
            assert output == {'allowed': True}

    @pytest.mark.parametrize("module_path,event_type", STANDARD_HOOKS)
    def test_exception_outputs_error(self, module_path, event_type):
        """When json.load fails, hook outputs error systemMessage and exits 0."""
        import importlib
        mod = importlib.import_module(module_path)

        mock_stdin = StringIO("NOT VALID JSON{{{")

        with patch.object(sys, 'stdin', mock_stdin), \
             patch('sys.stdout', new_callable=StringIO) as mock_stdout:

            with pytest.raises(SystemExit) as exc_info:
                mod.main()

            assert exc_info.value.code == 0
            output = json.loads(mock_stdout.getvalue())
            assert 'systemMessage' in output
            assert 'DB hook error' in output['systemMessage']


# ---------------------------------------------------------------------------
# SessionStart (health check variant)
# ---------------------------------------------------------------------------

class TestSessionStartHook:
    def test_healthy_calls_log_event(self):
        from hooks import db_sessionstart

        input_data = {'model': 'claude-sonnet', 'session_id': 's1'}
        mock_stdin = StringIO(json.dumps(input_data))

        with patch.object(sys, 'stdin', mock_stdin), \
             patch('hooks.db_sessionstart.check_health', return_value=(True, None)), \
             patch('hooks.db_sessionstart.log_event', return_value={}) as mock_log, \
             patch('sys.stdout', new_callable=StringIO):

            with pytest.raises(SystemExit) as exc_info:
                db_sessionstart.main()

            assert exc_info.value.code == 0
            mock_log.assert_called_once_with('SessionStart', input_data)

    def test_unhealthy_outputs_system_message(self):
        from hooks import db_sessionstart

        input_data = {'model': 'claude-sonnet'}
        mock_stdin = StringIO(json.dumps(input_data))

        with patch.object(sys, 'stdin', mock_stdin), \
             patch('hooks.db_sessionstart.check_health',
                   return_value=(False, '[telemetry] pyodbc not installed')), \
             patch('hooks.db_sessionstart.log_event') as mock_log, \
             patch('sys.stdout', new_callable=StringIO) as mock_stdout:

            with pytest.raises(SystemExit) as exc_info:
                db_sessionstart.main()

            assert exc_info.value.code == 0
            mock_log.assert_not_called()
            output = json.loads(mock_stdout.getvalue())
            assert output['systemMessage'] == '[telemetry] pyodbc not installed'

    def test_exception_outputs_startup_error(self):
        from hooks import db_sessionstart

        mock_stdin = StringIO("NOT VALID JSON{{{")

        with patch.object(sys, 'stdin', mock_stdin), \
             patch('sys.stdout', new_callable=StringIO) as mock_stdout:

            with pytest.raises(SystemExit) as exc_info:
                db_sessionstart.main()

            assert exc_info.value.code == 0
            output = json.loads(mock_stdout.getvalue())
            assert 'systemMessage' in output
            assert 'Startup error' in output['systemMessage']
