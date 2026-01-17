-- Claude Code Telemetry - Add Token Usage and Git Changes tracking
-- Run this if you already have the schema and need the new tables

USE ClaudeConversations;
GO

-- TokenUsage table for tracking tokens per message
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'TokenUsage')
BEGIN
    CREATE TABLE TokenUsage (
        UsageId BIGINT IDENTITY PRIMARY KEY,
        MessageId BIGINT NULL FOREIGN KEY REFERENCES Messages(MessageId),
        SessionId UNIQUEIDENTIFIER NOT NULL FOREIGN KEY REFERENCES Sessions(SessionId),
        MessageUuid NVARCHAR(100) NULL,
        Model NVARCHAR(100) NULL,
        InputTokens INT NULL,
        OutputTokens INT NULL,
        CacheCreationTokens INT NULL,
        CacheReadTokens INT NULL,
        ServiceTier NVARCHAR(50) NULL,
        EstimatedCostUsd DECIMAL(10,6) NULL,
        RecordedAt DATETIME2 DEFAULT GETUTCDATE()
    );
    CREATE INDEX IX_TokenUsage_SessionId ON TokenUsage(SessionId);
    CREATE INDEX IX_TokenUsage_MessageUuid ON TokenUsage(MessageUuid);
END
GO

-- GitChanges table for tracking file changes per session
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'GitChanges')
BEGIN
    CREATE TABLE GitChanges (
        ChangeId BIGINT IDENTITY PRIMARY KEY,
        SessionId UNIQUEIDENTIFIER NOT NULL FOREIGN KEY REFERENCES Sessions(SessionId),
        FilePath NVARCHAR(500) NOT NULL,
        ChangeType NVARCHAR(20) NOT NULL,  -- added, modified, deleted
        LinesAdded INT NULL,
        LinesDeleted INT NULL,
        DiffContent NVARCHAR(MAX) NULL,
        RecordedAt DATETIME2 DEFAULT GETUTCDATE()
    );
    CREATE INDEX IX_GitChanges_SessionId ON GitChanges(SessionId);
END
GO

PRINT 'Token usage and git changes tables added successfully';
GO
