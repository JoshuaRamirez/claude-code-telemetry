# Changelog

All notable changes to claude-code-telemetry.

## [1.0.0] - 2026-01-17

### Added
- Initial release with comprehensive SQL Server telemetry
- **8 hook event types**: PreToolUse, PostToolUse, UserPromptSubmit, Stop, SessionStart, SubagentStop, PreCompact, Notification
- **Tool timing**: DurationMs calculated by correlating PreToolUse/PostToolUse via tool_use_id
- **Full payload extraction**: ClaudeSessionId, TranscriptPath, Cwd, PermissionMode columns in HookEvents
- **Transcript parsing**: Messages table populated at session end with user/assistant content
- **Thinking blocks**: ThinkingContent captured separately from assistant responses
- **Concurrent session safety**: Session files keyed by claude_session_id to prevent collision
- **Session validation**: Stale session file detection when DB is truncated
- **Git context**: Branch and commit captured at SessionStart
- **Subagent tracking**: SubagentEvents table for Task agent completions
- **Context summarization**: CompactEvents table for PreCompact summaries
- **Notifications**: NotificationEvents table for system notifications

### Database Schema
- Sessions (with Model, GitBranch, GitCommit, WorkingDirectory)
- HookEvents (with ClaudeSessionId, TranscriptPath, Cwd, PermissionMode)
- ToolInvocations (with ToolUseId, StartedAt, CompletedAt, DurationMs, ToolResult)
- ToolParameters
- UserPrompts
- StopEvents
- Messages (with ThinkingContent)
- SubagentEvents
- CompactEvents
- NotificationEvents

### Scripts
- `scripts/install.ps1` - Windows installation (pyodbc, ODBC driver check, DB creation)
- `scripts/sync.ps1` - Development workflow (copy hooks to active location)

### Fixed
- Tool results now captured correctly (`tool_response` field, not `tool_result`)
- User prompts now captured correctly (`prompt` field, not `user_prompt`)
- PostToolUse updates existing PreToolUse record instead of creating duplicate
- Windows compatibility: `python` command instead of `python3`

---

## Development History

This plugin evolved through iterative development:

1. **Basic logging** - Initial PreToolUse/PostToolUse/Stop/UserPromptSubmit hooks
2. **Tool results gap** - Added ToolResult column and fixed field name
3. **Timing correlation** - Added tool_use_id tracking, StartedAt/CompletedAt/DurationMs
4. **Process isolation fix** - Moved timing from in-memory dict to DB-based correlation
5. **Concurrent sessions** - Session files keyed by claude_session_id
6. **Session validation** - Handle stale sessions after DB truncation
7. **New event types** - SessionStart, SubagentStop, PreCompact, Notification
8. **Full payload extraction** - ClaudeSessionId, TranscriptPath, Cwd, PermissionMode
9. **User prompt fix** - Correct field name from payload
10. **Windows compat** - python vs python3, sync script
