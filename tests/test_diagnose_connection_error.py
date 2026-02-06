"""Tests for _diagnose_connection_error() -- pure function, no mocking needed.

Target: hooks/health_check.py:83-124
"""

import pytest

from hooks.health_check import _diagnose_connection_error

pytestmark = pytest.mark.unit


class TestDriverNotFound:
    def test_driver_not_found(self):
        msg = _diagnose_connection_error("ODBC Driver not found")
        assert "ODBC Driver 17" in msg
        assert "Install from" in msg

    def test_driver_not_installed(self):
        msg = _diagnose_connection_error("ODBC Driver not installed on this system")
        assert "ODBC Driver 17" in msg


class TestDataSourceNotFound:
    def test_data_source_name_not_found(self):
        msg = _diagnose_connection_error("[IM002] Data source name not found")
        assert "ODBC driver not configured" in msg


class TestLoginFailed:
    def test_login_failed(self):
        msg = _diagnose_connection_error("Login failed for user 'sa'")
        assert "login failed" in msg.lower() or "SQL Server login" in msg

    def test_authentication_error(self):
        msg = _diagnose_connection_error("Authentication failure connecting to server")
        assert "login failed" in msg.lower() or "SQL Server login" in msg


class TestNetworkErrors:
    @pytest.mark.parametrize("phrase", [
        "Cannot open database 'ClaudeConversations'",
        "Server does not exist or access denied",
        "Connection refused by remote host",
        "TCP Provider: Error connecting",
        "Named Pipes Provider: Could not open",
        "A network-related error occurred",
        "Connection timeout expired",
    ])
    def test_network_phrases(self, phrase):
        msg = _diagnose_connection_error(phrase)
        assert "Cannot reach SQL Server" in msg


class TestFallback:
    def test_unrecognized_error(self):
        original = "Something completely unexpected happened"
        msg = _diagnose_connection_error(original)
        assert "Database connection failed" in msg
        assert original in msg
