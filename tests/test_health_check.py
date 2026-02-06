"""Tests for check_health() and _check_schema() -- import/connection mocking.

Target: hooks/health_check.py:29-80, :127-138

Note: check_health() does `import pyodbc` and `from db_logger import CONNECTION_STRING`
locally inside the function body, so we must patch pyodbc.connect on the actual
pyodbc module, not on hooks.health_check.
"""

import pytest
import pyodbc
from unittest.mock import patch, MagicMock

from hooks.health_check import check_health, _check_schema, REQUIRED_TABLES


pytestmark = pytest.mark.unit


class TestCheckHealthPyodbcMissing:
    def test_pyodbc_not_installed(self):
        """Mock builtins.__import__ to raise ImportError for pyodbc."""
        real_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        def fake_import(name, *args, **kwargs):
            if name == 'pyodbc':
                raise ImportError("No module named 'pyodbc'")
            return real_import(name, *args, **kwargs)

        with patch('builtins.__import__', side_effect=fake_import):
            healthy, msg = check_health()
            assert healthy is False
            assert "pyodbc not installed" in msg


class TestCheckHealthConnection:
    @patch('pyodbc.connect')
    def test_pyodbc_error(self, mock_connect):
        """pyodbc.Error during connect -> diagnosed message."""
        mock_connect.side_effect = pyodbc.Error("Login failed for user 'sa'")

        healthy, msg = check_health()
        assert healthy is False
        assert "SQL Server login" in msg or "login failed" in msg.lower()

    @patch('pyodbc.connect')
    def test_unexpected_exception(self, mock_connect):
        """Non-pyodbc exception during connect."""
        mock_connect.side_effect = RuntimeError("weird error")

        healthy, msg = check_health()
        assert healthy is False
        assert "Unexpected connection error" in msg


class TestCheckHealthSchema:
    @patch('hooks.health_check._check_schema')
    @patch('pyodbc.connect')
    def test_no_tables_found(self, mock_connect, mock_schema):
        mock_connect.return_value = MagicMock()
        mock_schema.return_value = []

        healthy, msg = check_health()
        assert healthy is False
        assert "No telemetry tables found" in msg

    @patch('hooks.health_check._check_schema')
    @patch('pyodbc.connect')
    def test_partial_tables_found(self, mock_connect, mock_schema):
        mock_connect.return_value = MagicMock()
        mock_schema.return_value = ['Sessions', 'HookEvents']  # missing 3

        healthy, msg = check_health()
        assert healthy is False
        assert "Schema incomplete" in msg
        assert "ToolInvocations" in msg

    @patch('hooks.health_check._check_schema')
    @patch('pyodbc.connect')
    def test_all_tables_present(self, mock_connect, mock_schema):
        mock_connect.return_value = MagicMock()
        mock_schema.return_value = list(REQUIRED_TABLES)

        healthy, msg = check_health()
        assert healthy is True
        assert msg is None

    @patch('hooks.health_check._check_schema', side_effect=Exception("SQL error"))
    @patch('pyodbc.connect')
    def test_schema_check_exception(self, mock_connect, mock_schema):
        mock_connect.return_value = MagicMock()

        healthy, msg = check_health()
        assert healthy is False
        assert "Schema check failed" in msg


class TestCheckSchema:
    def test_returns_found_tables(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [('Sessions',), ('HookEvents',)]

        result = _check_schema(mock_conn)
        assert result == ['Sessions', 'HookEvents']
        mock_cursor.execute.assert_called_once()

    def test_returns_empty_list(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = []

        result = _check_schema(mock_conn)
        assert result == []
