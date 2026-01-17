-- Claude Code Telemetry - Initial Schema
-- Run this against your SQL Server to create the ClaudeConversations database

-- Create database if not exists
IF NOT EXISTS (SELECT * FROM sys.databases WHERE name = 'ClaudeConversations')
BEGIN
    CREATE DATABASE ClaudeConversations;
END
GO

USE ClaudeConversations;
GO

-- Sessions table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Sessions')
BEGIN
    CREATE TABLE Sessions (
        SessionId UNIQUEIDENTIFIER PRIMARY KEY DEFAULT NEWID(),
        StartedAt DATETIME2 DEFAULT GETUTCDATE(),
        EndedAt DATETIME2 NULL,
        WorkingDirectory NVARCHAR(500) NULL,
        ProjectName NVARCHAR(200) NULL,
        Model NVARCHAR(100) NULL,
        GitBranch NVARCHAR(200) NULL,
        GitCommit NVARCHAR(50) NULL
    );
    CREATE INDEX IX_Sessions_StartedAt ON Sessions(StartedAt);
END
GO

-- HookEvents table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'HookEvents')
BEGIN
    CREATE TABLE HookEvents (
        EventId BIGINT IDENTITY PRIMARY KEY,
        SessionId UNIQUEIDENTIFIER NOT NULL FOREIGN KEY REFERENCES Sessions(SessionId),
        EventName NVARCHAR(50) NOT NULL,
        OccurredAt DATETIME2 DEFAULT GETUTCDATE(),
        RawJson NVARCHAR(MAX) NULL,
        ClaudeSessionId NVARCHAR(100) NULL,
        TranscriptPath NVARCHAR(500) NULL,
        Cwd NVARCHAR(500) NULL,
        PermissionMode NVARCHAR(50) NULL
    );
    CREATE INDEX IX_HookEvents_SessionId ON HookEvents(SessionId);
    CREATE INDEX IX_HookEvents_EventName ON HookEvents(EventName);
    CREATE INDEX IX_HookEvents_ClaudeSessionId ON HookEvents(ClaudeSessionId);
END
GO

-- ToolInvocations table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'ToolInvocations')
BEGIN
    CREATE TABLE ToolInvocations (
        InvocationId BIGINT IDENTITY PRIMARY KEY,
        EventId BIGINT NOT NULL FOREIGN KEY REFERENCES HookEvents(EventId),
        ToolName NVARCHAR(200) NOT NULL,
        WasBlocked BIT DEFAULT 0,
        BlockReason NVARCHAR(500) NULL,
        ToolResult NVARCHAR(MAX) NULL,
        ToolUseId NVARCHAR(100) NULL,
        StartedAt DATETIME2 NULL,
        CompletedAt DATETIME2 NULL,
        DurationMs INT NULL
    );
    CREATE INDEX IX_ToolInvocations_EventId ON ToolInvocations(EventId);
    CREATE INDEX IX_ToolInvocations_ToolName ON ToolInvocations(ToolName);
    CREATE INDEX IX_ToolInvocations_ToolUseId ON ToolInvocations(ToolUseId);
END
GO

-- ToolParameters table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'ToolParameters')
BEGIN
    CREATE TABLE ToolParameters (
        ParameterId BIGINT IDENTITY PRIMARY KEY,
        InvocationId BIGINT NOT NULL FOREIGN KEY REFERENCES ToolInvocations(InvocationId),
        ParamName NVARCHAR(200) NOT NULL,
        ParamValue NVARCHAR(MAX) NULL
    );
    CREATE INDEX IX_ToolParameters_InvocationId ON ToolParameters(InvocationId);
END
GO

-- UserPrompts table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'UserPrompts')
BEGIN
    CREATE TABLE UserPrompts (
        PromptId BIGINT IDENTITY PRIMARY KEY,
        EventId BIGINT NOT NULL FOREIGN KEY REFERENCES HookEvents(EventId),
        PromptText NVARCHAR(MAX) NULL
    );
    CREATE INDEX IX_UserPrompts_EventId ON UserPrompts(EventId);
END
GO

-- StopEvents table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'StopEvents')
BEGIN
    CREATE TABLE StopEvents (
        StopId BIGINT IDENTITY PRIMARY KEY,
        EventId BIGINT NOT NULL FOREIGN KEY REFERENCES HookEvents(EventId),
        Reason NVARCHAR(200) NULL,
        TranscriptPath NVARCHAR(500) NULL
    );
    CREATE INDEX IX_StopEvents_EventId ON StopEvents(EventId);
END
GO

-- Messages table (parsed from transcripts)
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'Messages')
BEGIN
    CREATE TABLE Messages (
        MessageId BIGINT IDENTITY PRIMARY KEY,
        SessionId UNIQUEIDENTIFIER NOT NULL FOREIGN KEY REFERENCES Sessions(SessionId),
        MessageUuid NVARCHAR(100) NULL,
        ParentUuid NVARCHAR(100) NULL,
        Role NVARCHAR(20) NOT NULL,
        Content NVARCHAR(MAX) NULL,
        ThinkingContent NVARCHAR(MAX) NULL,
        Model NVARCHAR(100) NULL,
        Timestamp DATETIME2 NULL
    );
    CREATE INDEX IX_Messages_SessionId ON Messages(SessionId);
    CREATE INDEX IX_Messages_Role ON Messages(Role);
    CREATE INDEX IX_Messages_MessageUuid ON Messages(MessageUuid);
END
GO

-- SubagentEvents table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'SubagentEvents')
BEGIN
    CREATE TABLE SubagentEvents (
        SubagentEventId BIGINT IDENTITY PRIMARY KEY,
        EventId BIGINT NOT NULL FOREIGN KEY REFERENCES HookEvents(EventId),
        AgentType NVARCHAR(100) NULL,
        TaskDescription NVARCHAR(MAX) NULL,
        Result NVARCHAR(MAX) NULL
    );
    CREATE INDEX IX_SubagentEvents_EventId ON SubagentEvents(EventId);
END
GO

-- CompactEvents table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'CompactEvents')
BEGIN
    CREATE TABLE CompactEvents (
        CompactEventId BIGINT IDENTITY PRIMARY KEY,
        EventId BIGINT NOT NULL FOREIGN KEY REFERENCES HookEvents(EventId),
        SummaryContent NVARCHAR(MAX) NULL
    );
    CREATE INDEX IX_CompactEvents_EventId ON CompactEvents(EventId);
END
GO

-- NotificationEvents table
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'NotificationEvents')
BEGIN
    CREATE TABLE NotificationEvents (
        NotificationEventId BIGINT IDENTITY PRIMARY KEY,
        EventId BIGINT NOT NULL FOREIGN KEY REFERENCES HookEvents(EventId),
        NotificationType NVARCHAR(100) NULL,
        NotificationContent NVARCHAR(MAX) NULL
    );
    CREATE INDEX IX_NotificationEvents_EventId ON NotificationEvents(EventId);
END
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
        ChangeType NVARCHAR(20) NOT NULL,
        LinesAdded INT NULL,
        LinesDeleted INT NULL,
        DiffContent NVARCHAR(MAX) NULL,
        RecordedAt DATETIME2 DEFAULT GETUTCDATE()
    );
    CREATE INDEX IX_GitChanges_SessionId ON GitChanges(SessionId);
END
GO

PRINT 'Claude Code Telemetry schema created successfully';
GO
