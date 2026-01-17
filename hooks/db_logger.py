#!/usr/bin/env python3
"""Database logger for Claude Code hook events.

Logs all hook events to SQL Server ClaudeConversations database.
"""

import json
import os
import sys
import subprocess
import pyodbc
from datetime import datetime
from typing import Dict, Any, Optional

# Database connection string
CONNECTION_STRING = (
    "Driver={ODBC Driver 17 for SQL Server};"
    "Server=localhost;"
    "Database=ClaudeConversations;"
    "Trusted_Connection=yes;"
)


def get_connection() -> Optional[pyodbc.Connection]:
    """Get database connection. Returns None on failure."""
    try:
        return pyodbc.connect(CONNECTION_STRING, timeout=5)
    except Exception as e:
        print(f"DB connection failed: {e}", file=sys.stderr)
        return None


def get_or_create_session(conn: pyodbc.Connection, working_dir: str = None,
                          project_name: str = None, claude_session_id: str = None) -> Optional[str]:
    """Get existing session or create new one. Returns SessionId as string.

    Args:
        conn: Database connection
        working_dir: Working directory for session
        project_name: Project name
        claude_session_id: Claude's session_id from hook payload for concurrent safety
    """
    from session_manager import get_session_id, set_session_id, clear_session_id

    session_id = get_session_id(claude_session_id)
    if session_id:
        # Validate session still exists in DB (may have been truncated)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM Sessions WHERE SessionId = ?", (session_id,))
        if cursor.fetchone():
            return session_id
        # Stale session file - clear it
        clear_session_id(claude_session_id)

    # Create new session
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO Sessions (WorkingDirectory, ProjectName)
        OUTPUT INSERTED.SessionId
        VALUES (?, ?)
    """, (working_dir or os.getcwd(), project_name))

    row = cursor.fetchone()
    conn.commit()

    if row:
        session_id = str(row[0])
        set_session_id(session_id, claude_session_id)
        return session_id
    return None


def log_hook_event(conn: pyodbc.Connection, session_id: str, event_name: str, raw_json: str,
                   claude_session_id: str = None, transcript_path: str = None,
                   cwd: str = None, permission_mode: str = None) -> Optional[int]:
    """Insert hook event and return EventId."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO HookEvents (SessionId, EventName, RawJson, ClaudeSessionId, TranscriptPath, Cwd, PermissionMode)
        OUTPUT INSERTED.EventId
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (session_id, event_name, raw_json, claude_session_id, transcript_path, cwd, permission_mode))

    row = cursor.fetchone()
    conn.commit()
    return row[0] if row else None


def log_tool_invocation(conn: pyodbc.Connection, event_id: int, tool_name: str,
                        tool_input: Dict[str, Any], was_blocked: bool = False,
                        block_reason: str = None, tool_result: str = None,
                        tool_use_id: str = None, started_at: datetime = None,
                        completed_at: datetime = None, duration_ms: int = None) -> Optional[int]:
    """Insert tool invocation and parameters. Returns InvocationId.

    Args:
        conn: Database connection
        event_id: Parent event ID
        tool_name: Name of the tool
        tool_input: Tool input parameters
        was_blocked: Whether tool was blocked
        block_reason: Reason for blocking
        tool_result: Tool execution result (PostToolUse)
        tool_use_id: Unique tool use ID for correlation
        started_at: When tool execution started
        completed_at: When tool execution completed
        duration_ms: Execution duration in milliseconds
    """
    cursor = conn.cursor()

    # Insert invocation with timing fields
    cursor.execute("""
        INSERT INTO ToolInvocations (EventId, ToolName, WasBlocked, BlockReason, ToolResult,
                                     ToolUseId, StartedAt, CompletedAt, DurationMs)
        OUTPUT INSERTED.InvocationId
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (event_id, tool_name, was_blocked, block_reason, tool_result,
          tool_use_id, started_at, completed_at, duration_ms))

    row = cursor.fetchone()
    if not row:
        conn.commit()
        return None

    invocation_id = row[0]

    # Insert parameters
    for param_name, param_value in tool_input.items():
        value_str = param_value if isinstance(param_value, str) else json.dumps(param_value)
        cursor.execute("""
            INSERT INTO ToolParameters (InvocationId, ParamName, ParamValue)
            VALUES (?, ?, ?)
        """, (invocation_id, param_name, value_str))

    conn.commit()
    return invocation_id


def log_user_prompt(conn: pyodbc.Connection, event_id: int, prompt_text: str) -> Optional[int]:
    """Insert user prompt. Returns PromptId."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO UserPrompts (EventId, PromptText)
        OUTPUT INSERTED.PromptId
        VALUES (?, ?)
    """, (event_id, prompt_text))

    row = cursor.fetchone()
    conn.commit()
    return row[0] if row else None


def log_stop_event(conn: pyodbc.Connection, event_id: int, reason: str, transcript_path: str = None) -> Optional[int]:
    """Insert stop event. Returns StopId."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO StopEvents (EventId, Reason, TranscriptPath)
        OUTPUT INSERTED.StopId
        VALUES (?, ?, ?)
    """, (event_id, reason, transcript_path))

    row = cursor.fetchone()
    conn.commit()
    return row[0] if row else None


def log_subagent_event(conn: pyodbc.Connection, event_id: int, agent_type: str,
                       task_description: str = None, result: str = None) -> Optional[int]:
    """Insert subagent event. Returns SubagentEventId."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO SubagentEvents (EventId, AgentType, TaskDescription, Result)
        OUTPUT INSERTED.SubagentEventId
        VALUES (?, ?, ?, ?)
    """, (event_id, agent_type, task_description, result))

    row = cursor.fetchone()
    conn.commit()
    return row[0] if row else None


def log_compact_event(conn: pyodbc.Connection, event_id: int, summary_content: str = None) -> Optional[int]:
    """Insert compact event. Returns CompactEventId."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO CompactEvents (EventId, SummaryContent)
        OUTPUT INSERTED.CompactEventId
        VALUES (?, ?)
    """, (event_id, summary_content))

    row = cursor.fetchone()
    conn.commit()
    return row[0] if row else None


def log_notification_event(conn: pyodbc.Connection, event_id: int,
                           notification_type: str = None, notification_content: str = None) -> Optional[int]:
    """Insert notification event. Returns NotificationEventId."""
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO NotificationEvents (EventId, NotificationType, NotificationContent)
        OUTPUT INSERTED.NotificationEventId
        VALUES (?, ?, ?)
    """, (event_id, notification_type, notification_content))

    row = cursor.fetchone()
    conn.commit()
    return row[0] if row else None


def update_session_metadata(conn: pyodbc.Connection, session_id: str,
                            model: str = None, git_branch: str = None, git_commit: str = None):
    """Update session with model and git info."""
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE Sessions
        SET Model = COALESCE(?, Model),
            GitBranch = COALESCE(?, GitBranch),
            GitCommit = COALESCE(?, GitCommit)
        WHERE SessionId = ?
    """, (model, git_branch, git_commit, session_id))
    conn.commit()


def get_git_info() -> tuple:
    """Get current git branch and commit. Returns (branch, commit) or (None, None)."""
    try:
        branch = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            capture_output=True, text=True, timeout=5
        )
        commit = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            capture_output=True, text=True, timeout=5
        )
        return (
            branch.stdout.strip() if branch.returncode == 0 else None,
            commit.stdout.strip() if commit.returncode == 0 else None
        )
    except Exception:
        return None, None


def parse_transcript(transcript_path: str) -> list:
    """Parse JSONL transcript file into list of messages.

    Captures text content, thinking blocks, and token usage from assistant messages.
    """
    messages = []
    try:
        with open(transcript_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    msg_type = obj.get('type')

                    if msg_type == 'user':
                        content = obj.get('message', {}).get('content', '')
                        # Content can be a string or list (tool results) - convert to string
                        if isinstance(content, list):
                            content = json.dumps(content)
                        messages.append({
                            'uuid': obj.get('uuid'),
                            'parent_uuid': obj.get('parentUuid'),
                            'role': 'user',
                            'content': content,
                            'model': None,
                            'timestamp': obj.get('timestamp'),
                            'thinking_content': None,
                            'usage': None
                        })

                    elif msg_type == 'assistant':
                        # Extract text and thinking from content array
                        msg_data = obj.get('message', {})
                        content_blocks = msg_data.get('content', [])
                        text_parts = []
                        thinking_parts = []

                        for block in content_blocks:
                            if isinstance(block, dict):
                                if block.get('type') == 'text':
                                    text_parts.append(block.get('text', ''))
                                elif block.get('type') == 'thinking':
                                    thinking_parts.append(block.get('thinking', ''))

                        # Extract usage data
                        usage = msg_data.get('usage', {})
                        usage_data = None
                        if usage:
                            usage_data = {
                                'input_tokens': usage.get('input_tokens'),
                                'output_tokens': usage.get('output_tokens'),
                                'cache_creation_tokens': usage.get('cache_creation_input_tokens'),
                                'cache_read_tokens': usage.get('cache_read_input_tokens'),
                                'service_tier': usage.get('service_tier')
                            }

                        if text_parts or thinking_parts or usage_data:
                            messages.append({
                                'uuid': obj.get('uuid'),
                                'parent_uuid': obj.get('parentUuid'),
                                'role': 'assistant',
                                'content': '\n'.join(text_parts) if text_parts else None,
                                'model': msg_data.get('model'),
                                'timestamp': obj.get('timestamp'),
                                'thinking_content': '\n'.join(thinking_parts) if thinking_parts else None,
                                'usage': usage_data
                            })
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"Error parsing transcript: {e}", file=sys.stderr)

    return messages


# Model pricing (USD per million tokens) - updated Jan 2026
MODEL_PRICING = {
    'claude-opus-4-5-20251101': {'input': 15.0, 'output': 75.0},
    'claude-sonnet-4-20250514': {'input': 3.0, 'output': 15.0},
    'claude-haiku-3-5-20241022': {'input': 0.80, 'output': 4.0},
    # Fallback for unknown models
    'default': {'input': 3.0, 'output': 15.0}
}


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate estimated cost in USD for token usage."""
    pricing = MODEL_PRICING.get(model, MODEL_PRICING['default'])
    input_cost = (input_tokens or 0) / 1_000_000 * pricing['input']
    output_cost = (output_tokens or 0) / 1_000_000 * pricing['output']
    return input_cost + output_cost


def log_token_usage(conn: pyodbc.Connection, session_id: str, messages: list):
    """Insert token usage records for messages with usage data."""
    cursor = conn.cursor()
    for msg in messages:
        usage = msg.get('usage')
        if not usage:
            continue

        msg_uuid = msg.get('uuid')
        model = msg.get('model')

        # Check if already logged
        if msg_uuid:
            cursor.execute("SELECT 1 FROM TokenUsage WHERE MessageUuid = ?", (msg_uuid,))
            if cursor.fetchone():
                continue

        # Calculate cost
        cost = calculate_cost(
            model,
            usage.get('input_tokens'),
            usage.get('output_tokens')
        )

        cursor.execute("""
            INSERT INTO TokenUsage (SessionId, MessageUuid, Model, InputTokens, OutputTokens,
                                    CacheCreationTokens, CacheReadTokens, ServiceTier, EstimatedCostUsd)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id,
            msg_uuid,
            model,
            usage.get('input_tokens'),
            usage.get('output_tokens'),
            usage.get('cache_creation_tokens'),
            usage.get('cache_read_tokens'),
            usage.get('service_tier'),
            cost
        ))
    conn.commit()


def capture_git_changes(conn: pyodbc.Connection, session_id: str):
    """Capture git diff for the session."""
    try:
        # Get list of changed files with stats
        result = subprocess.run(
            ['git', 'diff', '--numstat', 'HEAD'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return

        cursor = conn.cursor()
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            parts = line.split('\t')
            if len(parts) >= 3:
                added = int(parts[0]) if parts[0] != '-' else 0
                deleted = int(parts[1]) if parts[1] != '-' else 0
                filepath = parts[2]

                # Determine change type
                if added > 0 and deleted == 0:
                    change_type = 'added'
                elif deleted > 0 and added == 0:
                    change_type = 'deleted'
                else:
                    change_type = 'modified'

                cursor.execute("""
                    INSERT INTO GitChanges (SessionId, FilePath, ChangeType, LinesAdded, LinesDeleted)
                    VALUES (?, ?, ?, ?, ?)
                """, (session_id, filepath, change_type, added, deleted))

        conn.commit()
    except Exception as e:
        print(f"Git diff capture failed: {e}", file=sys.stderr)


def log_messages(conn: pyodbc.Connection, session_id: str, messages: list, deduplicate: bool = False):
    """Insert parsed messages into Messages table.

    Args:
        conn: Database connection
        session_id: Session ID
        messages: List of message dicts
        deduplicate: If True, skip messages that already exist (by MessageUuid)
    """
    cursor = conn.cursor()
    for msg in messages:
        msg_uuid = msg.get('uuid')

        # Skip if already exists (deduplication)
        if deduplicate and msg_uuid:
            cursor.execute("SELECT 1 FROM Messages WHERE MessageUuid = ?", (msg_uuid,))
            if cursor.fetchone():
                continue

        # Convert ISO timestamp string to naive datetime (SQL Server friendly)
        ts = msg.get('timestamp')
        if ts and isinstance(ts, str):
            # Parse ISO format: 2026-01-13T00:32:13.727Z -> naive datetime
            ts = ts.replace('Z', '').replace('T', ' ')
            # Truncate to microseconds precision for SQL Server
            if '.' in ts:
                ts = ts[:26]  # Keep up to 6 decimal places

        cursor.execute("""
            INSERT INTO Messages (SessionId, MessageUuid, ParentUuid, Role, Content, Model, Timestamp, ThinkingContent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id,
            msg_uuid,
            msg.get('parent_uuid'),
            msg.get('role'),
            msg.get('content'),
            msg.get('model'),
            ts,
            msg.get('thinking_content')
        ))
    conn.commit()


def close_session(conn: pyodbc.Connection, session_id: str):
    """Mark session as ended."""
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE Sessions SET EndedAt = GETUTCDATE() WHERE SessionId = ?
    """, (session_id,))
    conn.commit()


def update_tool_invocation(conn: pyodbc.Connection, tool_use_id: str,
                            tool_result: str = None, completed_at: datetime = None) -> bool:
    """Update existing tool invocation with result and timing. Returns True if updated."""
    if not tool_use_id:
        return False

    cursor = conn.cursor()

    # Get the PreToolUse record's StartedAt
    cursor.execute("""
        SELECT StartedAt FROM ToolInvocations
        WHERE ToolUseId = ? AND StartedAt IS NOT NULL
        ORDER BY InvocationId ASC
    """, (tool_use_id,))
    row = cursor.fetchone()

    if not row or not row[0]:
        return False

    started_at = row[0]
    duration_ms = None
    if completed_at and started_at:
        # started_at from DB is already datetime, completed_at is datetime
        delta = completed_at - started_at
        duration_ms = int(delta.total_seconds() * 1000)

    # Update the existing record
    cursor.execute("""
        UPDATE ToolInvocations
        SET ToolResult = ?, CompletedAt = ?, DurationMs = ?
        WHERE ToolUseId = ? AND StartedAt IS NOT NULL
    """, (tool_result, completed_at, duration_ms, tool_use_id))

    conn.commit()
    return cursor.rowcount > 0


def log_event(event_type: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Main entry point for logging any hook event.

    Args:
        event_type: One of 'PreToolUse', 'PostToolUse', 'Stop', 'UserPromptSubmit',
                   'SessionStart', 'SubagentStop', 'PreCompact', 'Notification'
        input_data: The JSON data passed to the hook

    Returns:
        Empty dict (always allow) or error message
    """
    conn = get_connection()
    if not conn:
        return {}  # Fail silently - don't block operations

    try:
        raw_json = json.dumps(input_data)

        # Extract common fields from all payloads
        claude_session_id = input_data.get('session_id')
        transcript_path = input_data.get('transcript_path')
        cwd = input_data.get('cwd')
        permission_mode = input_data.get('permission_mode')

        session_id = get_or_create_session(conn, claude_session_id=claude_session_id)

        if not session_id:
            return {}

        event_id = log_hook_event(conn, session_id, event_type, raw_json,
                                  claude_session_id=claude_session_id,
                                  transcript_path=transcript_path,
                                  cwd=cwd, permission_mode=permission_mode)
        if not event_id:
            return {}

        # Log type-specific data
        if event_type == 'PreToolUse':
            tool_name = input_data.get('tool_name', 'Unknown')
            tool_input = input_data.get('tool_input', {})
            tool_use_id = input_data.get('tool_use_id')
            started_at = datetime.utcnow()

            log_tool_invocation(conn, event_id, tool_name, tool_input,
                                tool_use_id=tool_use_id, started_at=started_at)

        elif event_type == 'PostToolUse':
            tool_use_id = input_data.get('tool_use_id')
            completed_at = datetime.utcnow()

            # Capture tool response
            tool_response_raw = input_data.get('tool_response')
            tool_result = None
            if tool_response_raw is not None:
                tool_result = tool_response_raw if isinstance(tool_response_raw, str) else json.dumps(tool_response_raw)

            # Update existing PreToolUse record with result and timing
            # This queries the DB for StartedAt and calculates duration
            update_tool_invocation(conn, tool_use_id, tool_result, completed_at)

            # Incrementally log messages and tokens after each tool (more frequent saves)
            if transcript_path:
                messages = parse_transcript(transcript_path)
                if messages:
                    log_messages(conn, session_id, messages, deduplicate=True)
                    log_token_usage(conn, session_id, messages)

        elif event_type == 'UserPromptSubmit':
            prompt = input_data.get('prompt', '')  # Field is 'prompt' not 'user_prompt'
            log_user_prompt(conn, event_id, prompt)

            # Incrementally log messages and tokens from transcript
            # This ensures responses are saved even if session is force-quit
            if transcript_path:
                messages = parse_transcript(transcript_path)
                if messages:
                    log_messages(conn, session_id, messages, deduplicate=True)
                    log_token_usage(conn, session_id, messages)

        elif event_type == 'Stop':
            reason = input_data.get('reason', '')
            transcript_path = input_data.get('transcript_path', '')
            log_stop_event(conn, event_id, reason, transcript_path)

            # Parse and store individual messages from transcript (dedupe with incremental logs)
            if transcript_path:
                messages = parse_transcript(transcript_path)
                if messages:
                    log_messages(conn, session_id, messages, deduplicate=True)
                    log_token_usage(conn, session_id, messages)

            # Capture git changes made during session
            capture_git_changes(conn, session_id)

            close_session(conn, session_id)

            # Clear session for next time
            from session_manager import clear_session_id
            clear_session_id(claude_session_id)

        elif event_type == 'SessionStart':
            # Extract model and git info, update session
            model = input_data.get('model')
            git_branch, git_commit = get_git_info()
            update_session_metadata(conn, session_id, model, git_branch, git_commit)

        elif event_type == 'SubagentStop':
            agent_type = input_data.get('agent_type', 'Unknown')
            task_description = input_data.get('task_description')
            result = input_data.get('result')
            if result is not None and not isinstance(result, str):
                result = json.dumps(result)
            log_subagent_event(conn, event_id, agent_type, task_description, result)

        elif event_type == 'PreCompact':
            summary_content = input_data.get('summary_content')
            if summary_content is not None and not isinstance(summary_content, str):
                summary_content = json.dumps(summary_content)
            log_compact_event(conn, event_id, summary_content)

        elif event_type == 'Notification':
            notification_type = input_data.get('notification_type')
            notification_content = input_data.get('notification_content')
            if notification_content is not None and not isinstance(notification_content, str):
                notification_content = json.dumps(notification_content)
            log_notification_event(conn, event_id, notification_type, notification_content)

        return {}

    except Exception as e:
        print(f"DB logging error: {e}", file=sys.stderr)
        return {}

    finally:
        conn.close()
