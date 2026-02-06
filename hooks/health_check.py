#!/usr/bin/env python3
"""Health check for claude-code-telemetry prerequisites.

Layered checks (short-circuits on first failure):
  1. pyodbc importable
  2. Database connection (distinguishes driver/auth/network errors)
  3. Schema tables present
"""

import sys
import os
from typing import Tuple, Optional

# Add hooks directory to path for db_logger import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PREFIX = "[claude-code-telemetry]"

# Core tables required for telemetry to function
REQUIRED_TABLES = [
    "Sessions",
    "HookEvents",
    "ToolInvocations",
    "Messages",
    "TokenUsage",
]


def check_health() -> Tuple[bool, Optional[str]]:
    """Run layered prerequisite checks.

    Returns:
        (True, None) if all checks pass.
        (False, "user-facing message") on first failure.
    """

    # Layer 1: pyodbc import
    try:
        import pyodbc
    except ImportError:
        return False, f"{PREFIX} pyodbc not installed. Run: pip install pyodbc"

    # Layer 2: Database connection
    from db_logger import CONNECTION_STRING

    conn = None
    try:
        conn = pyodbc.connect(CONNECTION_STRING, timeout=3)
    except pyodbc.Error as e:
        error_str = str(e)
        msg = _diagnose_connection_error(error_str)
        return False, f"{PREFIX} {msg}"
    except Exception as e:
        return False, f"{PREFIX} Unexpected connection error: {e}"

    # Layer 3: Schema validation
    try:
        found = _check_schema(conn)
        missing = [t for t in REQUIRED_TABLES if t not in found]

        if len(found) == 0:
            conn.close()
            return False, (
                f"{PREFIX} No telemetry tables found in database. "
                f"Run migrations/001_initial_schema.sql to create them."
            )

        if missing:
            conn.close()
            return False, (
                f"{PREFIX} Schema incomplete, missing: {', '.join(missing)}. "
                f"Run migrations/004_v2_schema.sql to update."
            )

    except Exception as e:
        conn.close()
        return False, f"{PREFIX} Schema check failed: {e}"

    conn.close()
    return True, None


def _diagnose_connection_error(error_str: str) -> str:
    """Inspect pyodbc error string to give specific guidance."""
    error_lower = error_str.lower()

    # ODBC driver not installed
    if "driver" in error_lower and ("not found" in error_lower or "not installed" in error_lower):
        return (
            "ODBC Driver 17 for SQL Server not found. "
            "Install from: https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server"
        )

    # Data source name not found (also driver issue)
    if "data source name not found" in error_lower:
        return (
            "ODBC driver not configured. "
            "Install ODBC Driver 17 for SQL Server."
        )

    # Login / authentication failure
    if "login failed" in error_lower or "authentication" in error_lower:
        return (
            "SQL Server login failed. Check that Trusted_Connection works "
            "or set CLAUDE_TELEMETRY_CONNECTION with valid credentials."
        )

    # Server unreachable / network
    if any(phrase in error_lower for phrase in [
        "cannot open database",
        "server does not exist",
        "connection refused",
        "tcp provider",
        "named pipes provider",
        "network",
        "timeout",
    ]):
        return (
            "Cannot reach SQL Server. Verify the server is running "
            "and connection string is correct (set CLAUDE_TELEMETRY_CONNECTION env var to override)."
        )

    # Fallback
    return f"Database connection failed: {error_str}"


def _check_schema(conn) -> list:
    """Query INFORMATION_SCHEMA for required tables. Returns list of found table names."""
    cursor = conn.cursor()
    placeholders = ", ".join("?" for _ in REQUIRED_TABLES)
    cursor.execute(f"""
        SELECT TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE'
          AND TABLE_NAME IN ({placeholders})
    """, REQUIRED_TABLES)

    return [row[0] for row in cursor.fetchall()]
