"""Shared fixtures for claude-code-telemetry unit tests.

Fixture layering:
    mock_cursor  →  mock_conn  →  patch_get_connection
    mock_subprocess_run (standalone)
    make_subprocess_result (factory)
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch

# Ensure hooks/ is importable as a package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'hooks'))


# ---------------------------------------------------------------------------
# Database mocks (layered)
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_cursor():
    """MagicMock cursor with sensible defaults.

    - fetchone() returns (1,) by default (simulates OUTPUT INSERTED)
    - fetchall() returns [] by default
    - rowcount = 1
    """
    cursor = MagicMock()
    cursor.fetchone.return_value = (1,)
    cursor.fetchall.return_value = []
    cursor.rowcount = 1
    return cursor


@pytest.fixture
def mock_conn(mock_cursor):
    """MagicMock connection whose .cursor() returns mock_cursor."""
    conn = MagicMock()
    conn.cursor.return_value = mock_cursor
    return conn


@pytest.fixture
def patch_get_connection(mock_conn):
    """Patch db_logger.get_connection to return mock_conn."""
    with patch('hooks.db_logger.get_connection', return_value=mock_conn) as p:
        yield p


# ---------------------------------------------------------------------------
# Subprocess mocks
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_subprocess_run():
    """Patch subprocess.run in db_logger module."""
    with patch('hooks.db_logger.subprocess.run') as mock_run:
        yield mock_run


def make_subprocess_result(stdout='', stderr='', returncode=0):
    """Factory for subprocess.CompletedProcess-like mocks."""
    result = MagicMock()
    result.stdout = stdout
    result.stderr = stderr
    result.returncode = returncode
    return result
