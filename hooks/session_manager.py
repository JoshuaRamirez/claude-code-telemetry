#!/usr/bin/env python3
"""Session ID manager for Claude Code hook events.

Tracks session ID across hook calls using temp files.
Supports concurrent Claude sessions via unique file names per claude_session_id.
"""

import os
import tempfile
from typing import Optional

# Base session file prefix
SESSION_FILE_PREFIX = 'claude_session_'
# Legacy session file for backwards compatibility
LEGACY_SESSION_FILE = os.path.join(tempfile.gettempdir(), 'claude_session_id')


def _get_session_file(claude_session_id: Optional[str] = None) -> str:
    """Get the session file path for a given claude session.

    Args:
        claude_session_id: Unique Claude session identifier from hook payload.
                          If None, returns legacy file path for backwards compatibility.

    Returns:
        Path to the session file.
    """
    if claude_session_id:
        return os.path.join(tempfile.gettempdir(), f'{SESSION_FILE_PREFIX}{claude_session_id}')
    return LEGACY_SESSION_FILE


def get_session_id(claude_session_id: Optional[str] = None) -> Optional[str]:
    """Get current session ID from temp file.

    Args:
        claude_session_id: Unique Claude session identifier from hook payload.
                          If None, uses legacy file path for backwards compatibility.

    Returns:
        Session ID string or None if not found.
    """
    session_file = _get_session_file(claude_session_id)
    try:
        if os.path.exists(session_file):
            with open(session_file, 'r') as f:
                session_id = f.read().strip()
                if session_id:
                    return session_id
    except Exception:
        pass
    return None


def set_session_id(session_id: str, claude_session_id: Optional[str] = None) -> None:
    """Store session ID to temp file.

    Args:
        session_id: The session ID to store.
        claude_session_id: Unique Claude session identifier from hook payload.
                          If None, uses legacy file path for backwards compatibility.
    """
    session_file = _get_session_file(claude_session_id)
    try:
        with open(session_file, 'w') as f:
            f.write(session_id)
    except Exception:
        pass


def clear_session_id(claude_session_id: Optional[str] = None) -> None:
    """Remove session ID file.

    Args:
        claude_session_id: Unique Claude session identifier from hook payload.
                          If None, uses legacy file path for backwards compatibility.
    """
    session_file = _get_session_file(claude_session_id)
    try:
        if os.path.exists(session_file):
            os.remove(session_file)
    except Exception:
        pass
