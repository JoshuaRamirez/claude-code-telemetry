# Claude Code Telemetry

Comprehensive SQL Server telemetry for Claude Code sessions. Track every interaction, tool usage, timing, thinking blocks, subagent executions, and full conversation history.

## What Gets Tracked

| Data | Hook | Table |
|------|------|-------|
| Your prompts | UserPromptSubmit | `UserPrompts` |
| Tool calls & parameters | PreToolUse | `ToolInvocations`, `ToolParameters` |
| Tool results & timing | PostToolUse | `ToolInvocations` (ToolResult, DurationMs) |
| Session metadata | SessionStart | `Sessions` (Model, GitBranch, GitCommit) |
| Subagent completions | SubagentStop | `SubagentEvents` |
| Context summarization | PreCompact | `CompactEvents` |
| System notifications | Notification | `NotificationEvents` |
| Full conversations | Stop | `Messages` (including ThinkingContent) |
| Raw hook payloads | All | `HookEvents.RawJson` |
| Working directory | All | `HookEvents.Cwd` |
| Permission mode | All | `HookEvents.PermissionMode` |
| Claude session ID | All | `HookEvents.ClaudeSessionId` |
| Transcript path | All | `HookEvents.TranscriptPath` |

## Requirements

- Python 3.8+
- SQL Server (local or remote)
- ODBC Driver 17 for SQL Server
- pyodbc

## Installation

### 1. Install Python Dependencies

```bash
pip install pyodbc
```

### 2. Create Database

Run the migration script against your SQL Server:

```bash
sqlcmd -S localhost -E -i migrations/001_initial_schema.sql
```

Or in SSMS, open and execute `migrations/001_initial_schema.sql`.

### 3. Configure Connection

Set environment variable for your connection string:

```bash
# Windows
set CLAUDE_TELEMETRY_CONNECTION="Driver={ODBC Driver 17 for SQL Server};Server=localhost;Database=ClaudeConversations;Trusted_Connection=yes;"

# Linux/Mac
export CLAUDE_TELEMETRY_CONNECTION="Driver={ODBC Driver 17 for SQL Server};Server=localhost;Database=ClaudeConversations;Trusted_Connection=yes;"
```

Or edit `hooks/db_logger.py` directly to set your connection string.

### 4. Install Plugin

```bash
# From plugin marketplace (if published)
/plugin marketplace add your-username/claude-code-telemetry

# Or install locally
/plugin install /path/to/claude-code-telemetry
```

## Schema

```
Sessions (1) ─────┬───── (*) HookEvents ─────┬───── (*) ToolInvocations ───── (*) ToolParameters
                  │                          ├───── (*) UserPrompts
                  │                          ├───── (*) StopEvents
                  │                          ├───── (*) SubagentEvents
                  │                          ├───── (*) CompactEvents
                  │                          └───── (*) NotificationEvents
                  │
                  └───── (*) Messages
```

## Useful Queries

### Session Overview
```sql
SELECT
    s.SessionId,
    s.StartedAt,
    s.EndedAt,
    s.Model,
    s.GitBranch,
    s.WorkingDirectory,
    (SELECT COUNT(*) FROM HookEvents WHERE SessionId = s.SessionId) AS EventCount,
    (SELECT COUNT(*) FROM Messages WHERE SessionId = s.SessionId) AS MessageCount
FROM Sessions s
ORDER BY s.StartedAt DESC;
```

### Tool Usage Stats
```sql
SELECT
    ToolName,
    COUNT(*) AS Uses,
    AVG(DurationMs) AS AvgMs,
    MAX(DurationMs) AS MaxMs,
    SUM(LEN(ToolResult)) / 1024 AS ResultKB
FROM ToolInvocations
WHERE DurationMs IS NOT NULL
GROUP BY ToolName
ORDER BY Uses DESC;
```

### Recent Prompts
```sql
SELECT TOP 20
    s.StartedAt,
    LEFT(up.PromptText, 200) AS Prompt
FROM UserPrompts up
JOIN HookEvents he ON up.EventId = he.EventId
JOIN Sessions s ON he.SessionId = s.SessionId
ORDER BY he.EventId DESC;
```

### Thinking Block Analysis
```sql
SELECT
    m.Role,
    LEFT(m.Content, 100) AS ContentPreview,
    LEFT(m.ThinkingContent, 200) AS ThinkingPreview,
    LEN(m.ThinkingContent) AS ThinkingLength
FROM Messages m
WHERE m.ThinkingContent IS NOT NULL
ORDER BY m.MessageId DESC;
```

## Architecture

```
Claude Code Session
        │
        ├─► PreToolUse ──────► db_pretooluse.py ──┐
        ├─► PostToolUse ─────► db_posttooluse.py ─┤
        ├─► UserPromptSubmit ► db_userpromptsubmit.py
        ├─► SessionStart ────► db_sessionstart.py ├──► db_logger.py ──► SQL Server
        ├─► SubagentStop ────► db_subagentstop.py ┤
        ├─► PreCompact ──────► db_precompact.py ──┤
        ├─► Notification ────► db_notification.py ┤
        └─► Stop ────────────► db_stop.py ────────┘
```

## Features

- **Tool Correlation**: PreToolUse and PostToolUse linked via `tool_use_id`
- **Timing**: Automatic duration calculation for every tool call
- **Concurrent Sessions**: Safe handling of multiple Claude instances
- **Thinking Capture**: Extended thinking blocks stored separately
- **Git Context**: Branch and commit captured at session start
- **Fail-Safe**: Errors logged to stderr, never blocks Claude operations

## Development

After making changes to the repo, sync to your active hooks:

```powershell
.\scripts\sync.ps1
```

Changes take effect immediately - no restart needed.

### Migrations

If upgrading from an older version, run any new migration scripts:

```bash
sqlcmd -S localhost -E -i migrations/002_add_hookevents_columns.sql
```

## License

MIT
