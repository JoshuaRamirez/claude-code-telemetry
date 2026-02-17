#!/usr/bin/env python3
"""Database logger for Claude Code hook events - v2.

Logs all hook events to SQL Server ClaudeConversations database.

v2 fixes:
- Session lookup via DB (ClaudeSessionId) instead of temp files
- Incremental transcript parsing with position tracking
- Transaction boundaries for multi-INSERT operations
- Tool correlation race condition fix
- JSON storage for tool inputs (replaces EAV)
- TriggerEventId linking messages to events
- Incremental git capture on Write/Edit tools
"""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from typing import Any, Optional

import pyodbc

# Database connection string (override via CLAUDE_TELEMETRY_CONNECTION env var)
CONNECTION_STRING = os.environ.get(
    'CLAUDE_TELEMETRY_CONNECTION',
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

    v2: Looks up session directly in database by ClaudeSessionId.
    v2.1: Three-step approach handles /resume with IntegrityError fallback.

    Steps:
        1. Find active session by ClaudeSessionId
        2. Try to create new session (IntegrityError on duplicate ClaudeSessionId)
        3. If INSERT failed (duplicate), reopen the ended session (/resume case)

    Args:
        conn: Database connection
        working_dir: Working directory for session
        project_name: Project name
        claude_session_id: Claude's session_id from hook payload for concurrent safety
    """
    cursor = conn.cursor()

    # Step 1: Find active (non-ended) session by ClaudeSessionId
    if claude_session_id:
        cursor.execute("""
            SELECT SessionId FROM Sessions
            WHERE ClaudeSessionId = ? AND EndedAt IS NULL
        """, (claude_session_id,))
        row = cursor.fetchone()
        if row:
            return str(row[0])

    # Step 2: Try to create new session
    try:
        cursor.execute("""
            INSERT INTO Sessions (WorkingDirectory, ProjectName, ClaudeSessionId)
            OUTPUT INSERTED.SessionId
            VALUES (?, ?, ?)
        """, (working_dir or os.getcwd(), project_name, claude_session_id))

        row = cursor.fetchone()
        conn.commit()

        if row:
            return str(row[0])
    except pyodbc.IntegrityError:
        # Duplicate ClaudeSessionId — session exists (possibly ended).
        # Rollback the failed statement to ensure clean transaction state
        # (defensive: needed if XACT_ABORT is ever set to ON).
        conn.rollback()
        # Fall through to Step 3 to reopen it.

    # Step 3: INSERT failed (IntegrityError) — session exists but ended.
    # This is the /resume case: reopen the ended session.
    if claude_session_id:
        cursor.execute("""
            UPDATE Sessions SET EndedAt = NULL
            OUTPUT INSERTED.SessionId
            WHERE ClaudeSessionId = ?
        """, (claude_session_id,))
        row = cursor.fetchone()
        conn.commit()
        if row:
            return str(row[0])

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
                        tool_input: dict[str, Any], was_blocked: bool = False,
                        block_reason: str = None, tool_result: str = None,
                        tool_use_id: str = None, started_at: datetime = None,
                        completed_at: datetime = None, duration_ms: int = None) -> Optional[int]:
    """Insert tool invocation with JSON parameters. Returns InvocationId.

    v2: Stores tool_input as JSON in ToolInputJson column instead of EAV rows.

    Args:
        conn: Database connection
        event_id: Parent event ID
        tool_name: Name of the tool
        tool_input: Tool input parameters (stored as JSON)
        was_blocked: Whether tool was blocked
        block_reason: Reason for blocking
        tool_result: Tool execution result (PostToolUse)
        tool_use_id: Unique tool use ID for correlation
        started_at: When tool execution started
        completed_at: When tool execution completed
        duration_ms: Execution duration in milliseconds
    """
    cursor = conn.cursor()

    # Convert tool_input dict to JSON string
    tool_input_json = json.dumps(tool_input) if tool_input else None

    try:
        cursor.execute("BEGIN TRANSACTION")

        # Insert invocation with JSON parameter storage
        cursor.execute("""
            INSERT INTO ToolInvocations (EventId, ToolName, WasBlocked, BlockReason, ToolResult,
                                         ToolUseId, StartedAt, CompletedAt, DurationMs, ToolInputJson)
            OUTPUT INSERTED.InvocationId
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (event_id, tool_name, was_blocked, block_reason, tool_result,
              tool_use_id, started_at, completed_at, duration_ms, tool_input_json))

        row = cursor.fetchone()
        invocation_id = row[0] if row else None

        cursor.execute("COMMIT")
        return invocation_id

    except Exception as e:
        cursor.execute("ROLLBACK")
        print(f"Tool invocation insert failed: {e}", file=sys.stderr)
        return None


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


def log_stop_event(conn: pyodbc.Connection, event_id: int, reason: str) -> Optional[int]:
    """Insert stop event. Returns StopId.

    v2: TranscriptPath removed (redundant with HookEvents).
    """
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO StopEvents (EventId, Reason)
        OUTPUT INSERTED.StopId
        VALUES (?, ?)
    """, (event_id, reason))

    row = cursor.fetchone()
    conn.commit()
    return row[0] if row else None


def log_subagent_event(conn: pyodbc.Connection, event_id: int, agent_type: str,
                       task_description: str = None, result: str = None,
                       tool_use_id: str = None) -> Optional[int]:
    """Insert subagent event. Returns SubagentEventId.

    Args:
        tool_use_id: Links to the parent Task tool invocation in ToolInvocations.
    """
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO SubagentEvents (EventId, AgentType, TaskDescription, Result, ToolUseId)
        OUTPUT INSERTED.SubagentEventId
        VALUES (?, ?, ?, ?, ?)
    """, (event_id, agent_type, task_description, result, tool_use_id))

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


def get_git_info() -> tuple[Optional[str], Optional[str]]:
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


def parse_transcript_incremental(conn: pyodbc.Connection, session_id: str,
                                  transcript_path: str) -> list[dict[str, Any]]:
    """Parse only new lines from transcript since last position.

    v2: Tracks file position in Sessions.LastTranscriptPosition.
    Eliminates O(n²) re-parsing - now O(n) over session lifetime.

    Args:
        conn: Database connection
        session_id: Session ID for position tracking
        transcript_path: Path to JSONL transcript file

    Returns:
        List of newly parsed message dicts
    """
    cursor = conn.cursor()

    # Get last position from DB
    cursor.execute("SELECT LastTranscriptPosition FROM Sessions WHERE SessionId = ?", (session_id,))
    row = cursor.fetchone()
    last_position = row[0] if row and row[0] else 0

    messages = []
    try:
        with open(transcript_path, encoding='utf-8') as f:
            f.seek(last_position)
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    msg = _parse_transcript_line(obj)
                    if msg:
                        messages.append(msg)
                except json.JSONDecodeError:
                    continue
            new_position = f.tell()

        # Update position in DB
        cursor.execute("""
            UPDATE Sessions SET LastTranscriptPosition = ?
            WHERE SessionId = ?
        """, (new_position, session_id))
        conn.commit()

    except Exception as e:
        print(f"Error parsing transcript: {e}", file=sys.stderr)

    return messages


def _parse_transcript_line(obj: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Parse a single transcript line into a message dict.

    Handles: user, assistant, system, queue-operation, file-history-snapshot.
    Skips: progress (streaming noise), saved_hook_context.
    """
    msg_type = obj.get('type')

    if msg_type == 'user':
        content = obj.get('message', {}).get('content', '')
        if isinstance(content, list):
            # Extract text from content blocks instead of raw JSON dump
            text_parts = []
            for item in content:
                if isinstance(item, str):
                    text_parts.append(item)
                elif isinstance(item, dict) and item.get('type') == 'text':
                    text_parts.append(item.get('text', ''))
            content = '\n'.join(text_parts) if text_parts else json.dumps(content)
        return {
            'uuid': obj.get('uuid'),
            'parent_uuid': obj.get('parentUuid'),
            'role': 'user',
            'content': content,
            'model': None,
            'timestamp': obj.get('timestamp'),
            'thinking_content': None,
            'usage': None,
            'content_blocks_json': None
        }

    elif msg_type == 'assistant':
        msg_data = obj.get('message', {})
        content_blocks = msg_data.get('content', [])
        text_parts = []
        thinking_parts = []
        tool_use_parts = []

        for block in content_blocks:
            if isinstance(block, dict):
                if block.get('type') == 'text':
                    text_parts.append(block.get('text', ''))
                elif block.get('type') == 'thinking':
                    thinking_parts.append(block.get('thinking', ''))
                elif block.get('type') == 'tool_use':
                    tool_use_parts.append({
                        'type': 'tool_use',
                        'id': block.get('id'),
                        'name': block.get('name'),
                        'input': block.get('input')
                    })

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

        if text_parts or thinking_parts or tool_use_parts or usage_data:
            # Preserve thinking block boundaries: single = plain text, multiple = JSON array
            if len(thinking_parts) > 1:
                thinking_content = json.dumps(thinking_parts)
            elif thinking_parts:
                thinking_content = thinking_parts[0]
            else:
                thinking_content = None

            return {
                'uuid': obj.get('uuid'),
                'parent_uuid': obj.get('parentUuid'),
                'role': 'assistant',
                'content': '\n'.join(text_parts) if text_parts else None,
                'model': msg_data.get('model'),
                'timestamp': obj.get('timestamp'),
                'thinking_content': thinking_content,
                'usage': usage_data,
                'content_blocks_json': json.dumps(content_blocks) if content_blocks else None
            }

    elif msg_type == 'system':
        return {
            'uuid': None,
            'parent_uuid': None,
            'role': 'system',
            'content': json.dumps(obj),
            'model': None,
            'timestamp': obj.get('timestamp'),
            'thinking_content': None,
            'usage': None,
            'content_blocks_json': None
        }

    elif msg_type == 'queue-operation':
        content = obj.get('content')
        if content is None:
            content = json.dumps(obj)
        elif not isinstance(content, str):
            content = json.dumps(content)
        return {
            'uuid': None,
            'parent_uuid': None,
            'role': 'queue_operation',
            'content': content,
            'model': None,
            'timestamp': obj.get('timestamp'),
            'thinking_content': None,
            'usage': None,
            'content_blocks_json': None
        }

    elif msg_type == 'file-history-snapshot':
        return {
            'uuid': None,
            'parent_uuid': None,
            'role': 'file_history',
            'content': json.dumps(obj),
            'model': None,
            'timestamp': obj.get('timestamp'),
            'thinking_content': None,
            'usage': None,
            'content_blocks_json': None
        }

    # Skip: progress (streaming noise), saved_hook_context, unknown types
    return None


def parse_transcript(transcript_path: str) -> list[dict[str, Any]]:
    """Parse full JSONL transcript file into list of messages.

    Legacy function - use parse_transcript_incremental for production.
    Kept for Stop event final capture.
    """
    messages = []
    try:
        with open(transcript_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    msg = _parse_transcript_line(obj)
                    if msg:
                        messages.append(msg)
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
    'default': {'input': 3.0, 'output': 15.0}
}


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate estimated cost in USD for token usage."""
    pricing = MODEL_PRICING.get(model, MODEL_PRICING['default'])
    input_cost = (input_tokens or 0) / 1_000_000 * pricing['input']
    output_cost = (output_tokens or 0) / 1_000_000 * pricing['output']
    return input_cost + output_cost


def log_token_usage(conn: pyodbc.Connection, session_id: str, messages: list[dict[str, Any]]):
    """Insert token usage records for messages with usage data."""
    cursor = conn.cursor()
    for msg in messages:
        usage = msg.get('usage')
        if not usage:
            continue

        msg_uuid = msg.get('uuid')
        model = msg.get('model')

        cost = calculate_cost(
            model,
            usage.get('input_tokens'),
            usage.get('output_tokens')
        )

        try:
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
        except pyodbc.IntegrityError:
            # Duplicate MessageUuid — already exists, skip.
            conn.rollback()  # Clean transaction state (defensive)
            continue
    conn.commit()


def capture_git_changes(conn: pyodbc.Connection, session_id: str):
    """Capture git diff for the session.

    Uses MERGE (upsert) so calling multiple times (e.g. Stop + SessionEnd)
    updates existing rows instead of creating duplicates.
    """
    try:
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

                if added > 0 and deleted == 0:
                    change_type = 'added'
                elif deleted > 0 and added == 0:
                    change_type = 'deleted'
                else:
                    change_type = 'modified'

                cursor.execute("""
                    MERGE GitChanges AS target
                    USING (SELECT ? AS SessionId, ? AS FilePath) AS source
                    ON target.SessionId = source.SessionId AND target.FilePath = source.FilePath
                    WHEN MATCHED THEN
                        UPDATE SET ChangeType = ?, LinesAdded = ?, LinesDeleted = ?, RecordedAt = GETUTCDATE()
                    WHEN NOT MATCHED THEN
                        INSERT (SessionId, FilePath, ChangeType, LinesAdded, LinesDeleted)
                        VALUES (?, ?, ?, ?, ?);
                """, (session_id, filepath, change_type, added, deleted,
                      session_id, filepath, change_type, added, deleted))

        conn.commit()
    except Exception as e:
        print(f"Git diff capture failed: {e}", file=sys.stderr)


def capture_git_changes_incremental(conn: pyodbc.Connection, session_id: str, filepath: str = None):
    """Capture git changes incrementally after file operations.

    v2: Called after Write/Edit tools to capture changes before potential crash.

    Args:
        conn: Database connection
        session_id: Session ID
        filepath: Optional specific file to check (for targeted capture)
    """
    try:
        cmd = ['git', 'diff', '--numstat', 'HEAD']
        if filepath:
            cmd.append('--')
            cmd.append(filepath)

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
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
                fp = parts[2]

                if added > 0 and deleted == 0:
                    change_type = 'added'
                elif deleted > 0 and added == 0:
                    change_type = 'deleted'
                else:
                    change_type = 'modified'

                # Upsert - update if exists, insert if new
                cursor.execute("""
                    MERGE GitChanges AS target
                    USING (SELECT ? AS SessionId, ? AS FilePath) AS source
                    ON target.SessionId = source.SessionId AND target.FilePath = source.FilePath
                    WHEN MATCHED THEN
                        UPDATE SET ChangeType = ?, LinesAdded = ?, LinesDeleted = ?, RecordedAt = GETUTCDATE()
                    WHEN NOT MATCHED THEN
                        INSERT (SessionId, FilePath, ChangeType, LinesAdded, LinesDeleted)
                        VALUES (?, ?, ?, ?, ?);
                """, (session_id, fp, change_type, added, deleted,
                      session_id, fp, change_type, added, deleted))

        conn.commit()
    except Exception as e:
        print(f"Incremental git capture failed: {e}", file=sys.stderr)


def log_messages(conn: pyodbc.Connection, session_id: str, messages: list[dict[str, Any]],
                 trigger_event_id: int = None):
    """Insert parsed messages into Messages table.

    Deduplication is handled automatically by the unique filtered index on
    Messages.MessageUuid — duplicate INSERTs raise IntegrityError and are skipped.
    NULL-uuid rows (system/queue) always insert (excluded from unique index).

    Args:
        conn: Database connection
        session_id: Session ID
        messages: List of message dicts
        trigger_event_id: EventId that triggered this message logging
    """
    cursor = conn.cursor()
    for msg in messages:
        msg_uuid = msg.get('uuid')

        ts = msg.get('timestamp')
        if ts and isinstance(ts, str):
            ts = ts.replace('Z', '').replace('T', ' ')
            if '.' in ts:
                ts = ts[:26]

        try:
            cursor.execute("""
                INSERT INTO Messages (SessionId, MessageUuid, ParentUuid, Role, Content,
                                      Model, Timestamp, ThinkingContent, TriggerEventId, ContentBlocksJson)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                session_id,
                msg_uuid,
                msg.get('parent_uuid'),
                msg.get('role'),
                msg.get('content'),
                msg.get('model'),
                ts,
                msg.get('thinking_content'),
                trigger_event_id,
                msg.get('content_blocks_json')
            ))
        except pyodbc.IntegrityError:
            # Duplicate MessageUuid — already exists, skip.
            # NULL-uuid rows (system/queue) always insert (not in unique index).
            conn.rollback()  # Clean transaction state (defensive)
            continue
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
    """Update existing tool invocation with result and timing.

    v2: Fixed race condition - only updates if not already completed.

    Returns True if updated.
    """
    if not tool_use_id:
        return False

    cursor = conn.cursor()

    # Get the PreToolUse record's StartedAt
    cursor.execute("""
        SELECT StartedAt FROM ToolInvocations
        WHERE ToolUseId = ?
          AND StartedAt IS NOT NULL
          AND CompletedAt IS NULL
        ORDER BY InvocationId ASC
    """, (tool_use_id,))
    row = cursor.fetchone()

    if not row or not row[0]:
        return False

    started_at = row[0]
    duration_ms = None
    if completed_at and started_at:
        delta = completed_at - started_at
        duration_ms = int(delta.total_seconds() * 1000)

    # Update the existing record - only if not already completed
    cursor.execute("""
        UPDATE ToolInvocations
        SET ToolResult = ?, CompletedAt = ?, DurationMs = ?
        WHERE ToolUseId = ?
          AND StartedAt IS NOT NULL
          AND CompletedAt IS NULL
    """, (tool_result, completed_at, duration_ms, tool_use_id))

    conn.commit()
    return cursor.rowcount > 0


def log_event(event_type: str, input_data: dict[str, Any]) -> dict[str, Any]:
    """Main entry point for logging any hook event.

    Args:
        event_type: One of 'PreToolUse', 'PostToolUse', 'Stop', 'SessionEnd',
                   'UserPromptSubmit', 'SessionStart', 'SubagentStop',
                   'PreCompact', 'Notification'
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
            started_at = datetime.now(UTC)

            log_tool_invocation(conn, event_id, tool_name, tool_input,
                                tool_use_id=tool_use_id, started_at=started_at)

        elif event_type == 'PostToolUse':
            tool_name = input_data.get('tool_name')
            tool_use_id = input_data.get('tool_use_id')
            completed_at = datetime.now(UTC)

            # Capture tool response
            tool_response_raw = input_data.get('tool_response')
            tool_result = None
            if tool_response_raw is not None:
                tool_result = tool_response_raw if isinstance(tool_response_raw, str) else json.dumps(tool_response_raw)

            # Update existing PreToolUse record with result and timing
            update_tool_invocation(conn, tool_use_id, tool_result, completed_at)

            # v2: Capture git changes incrementally for Write/Edit tools
            if tool_name in ('Write', 'Edit', 'NotebookEdit'):
                file_path = input_data.get('tool_input', {}).get('file_path')
                capture_git_changes_incremental(conn, session_id, file_path)

            # Incrementally log messages and tokens (with position tracking)
            if transcript_path:
                messages = parse_transcript_incremental(conn, session_id, transcript_path)
                if messages:
                    log_messages(conn, session_id, messages, trigger_event_id=event_id)
                    log_token_usage(conn, session_id, messages)

        elif event_type == 'UserPromptSubmit':
            prompt = input_data.get('prompt') or input_data.get('user_prompt', '')
            log_user_prompt(conn, event_id, prompt)

            # Incrementally log messages and tokens
            if transcript_path:
                messages = parse_transcript_incremental(conn, session_id, transcript_path)
                if messages:
                    log_messages(conn, session_id, messages, trigger_event_id=event_id)
                    log_token_usage(conn, session_id, messages)

        elif event_type == 'Stop':
            reason = input_data.get('reason', '')
            log_stop_event(conn, event_id, reason)

            # Final full parse to ensure nothing missed (dedupes with incremental)
            if transcript_path:
                messages = parse_transcript(transcript_path)
                if messages:
                    log_messages(conn, session_id, messages, trigger_event_id=event_id)
                    log_token_usage(conn, session_id, messages)

            # Capture git changes (not final — session may continue or resume)
            capture_git_changes(conn, session_id)
            # NOTE: close_session moved to SessionEnd handler (Phase 4).
            # Stop events don't close sessions because the user may continue.

        elif event_type == 'SessionStart':
            model = input_data.get('model')
            git_branch, git_commit = get_git_info()
            update_session_metadata(conn, session_id, model, git_branch, git_commit)

        elif event_type == 'SubagentStop':
            agent_type = input_data.get('agent_type', 'Unknown')
            task_description = input_data.get('task_description')
            tool_use_id = input_data.get('tool_use_id')
            result = input_data.get('result')
            if result is not None and not isinstance(result, str):
                result = json.dumps(result)
            log_subagent_event(conn, event_id, agent_type, task_description, result,
                               tool_use_id=tool_use_id)

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

        elif event_type == 'SessionEnd':
            # Final full parse to ensure nothing missed
            if transcript_path:
                messages = parse_transcript(transcript_path)
                if messages:
                    log_messages(conn, session_id, messages, trigger_event_id=event_id)
                    log_token_usage(conn, session_id, messages)
            # Capture final git changes
            capture_git_changes(conn, session_id)
            # Authoritative session close — only SessionEnd sets EndedAt
            close_session(conn, session_id)

        return {}

    except Exception as e:
        print(f"DB logging error: {e}", file=sys.stderr)
        return {}

    finally:
        conn.close()
