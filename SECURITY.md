# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 2.0.x   | Yes                |
| < 2.0   | No                 |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly:

1. **Do not** open a public issue.
2. Email **joshua.ramirez@me.com** with details.
3. Include steps to reproduce, if possible.
4. You will receive a response within 48 hours.

## Security Considerations

### Database Access
- The plugin connects to SQL Server via ODBC with credentials from the `CLAUDE_TELEMETRY_CONNECTION` environment variable.
- Default configuration uses Windows Trusted Authentication (no password in connection string).
- If using SQL authentication, ensure the connection string is stored securely and not committed to version control.

### Environment Variables
- `CLAUDE_TELEMETRY_CONNECTION` may contain sensitive connection details.
- This variable should be set at the user level, not system-wide.

### Data Stored
- The plugin logs prompts, tool usage, and conversation content to SQL Server.
- Transcript data may contain sensitive information from your Claude Code sessions.
- Ensure your SQL Server instance has appropriate access controls.

### Hook Execution
- All hooks run as local Python scripts with the same permissions as your user account.
- Hook scripts are read-only consumers of Claude Code event data -- they do not modify Claude's behavior.
- The `PreToolUse` hook always returns `{"decision": "approve"}` and does not block any tools.
