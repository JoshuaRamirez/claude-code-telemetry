-- Claude Code Telemetry - Add HookEvents payload columns
-- Run this if you already have the initial schema and need the new columns

USE ClaudeConversations;
GO

-- Add new columns to HookEvents for full payload extraction
IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('HookEvents') AND name = 'ClaudeSessionId')
BEGIN
    ALTER TABLE HookEvents ADD ClaudeSessionId NVARCHAR(100) NULL;
END
GO

IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('HookEvents') AND name = 'TranscriptPath')
BEGIN
    ALTER TABLE HookEvents ADD TranscriptPath NVARCHAR(500) NULL;
END
GO

IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('HookEvents') AND name = 'Cwd')
BEGIN
    ALTER TABLE HookEvents ADD Cwd NVARCHAR(500) NULL;
END
GO

IF NOT EXISTS (SELECT * FROM sys.columns WHERE object_id = OBJECT_ID('HookEvents') AND name = 'PermissionMode')
BEGIN
    ALTER TABLE HookEvents ADD PermissionMode NVARCHAR(50) NULL;
END
GO

-- Add index on ClaudeSessionId for correlation queries
IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_HookEvents_ClaudeSessionId')
BEGIN
    CREATE INDEX IX_HookEvents_ClaudeSessionId ON HookEvents(ClaudeSessionId);
END
GO

PRINT 'HookEvents columns added successfully';
GO
