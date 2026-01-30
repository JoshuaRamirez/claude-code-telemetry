-- Migration 004: Claude Code Telemetry v2 - Database & Data Flow Fixes
-- Fixes 10 identified issues: dual session ID, O(n²) parsing, FK integrity,
-- data loss, atomicity, correlation, concurrency, redundancy, EAV pattern, indexes
--
-- Run: sqlcmd -S localhost -E -d ClaudeConversations -i 004_v2_schema.sql

SET XACT_ABORT ON;
BEGIN TRANSACTION;

PRINT 'Starting migration 004_v2_schema...';

------------------------------------------------------------
-- 1. Unify Session Identity
-- Add ClaudeSessionId for direct DB lookup (eliminates temp files)
------------------------------------------------------------
IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('Sessions') AND name = 'ClaudeSessionId'
)
BEGIN
    ALTER TABLE Sessions ADD ClaudeSessionId NVARCHAR(100) NULL;
    PRINT 'Added Sessions.ClaudeSessionId column';
END
ELSE
    PRINT 'Sessions.ClaudeSessionId already exists';
GO

-- Create unique index for fast session lookup
IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID('Sessions') AND name = 'UX_Sessions_ClaudeSessionId'
)
BEGIN
    CREATE UNIQUE INDEX UX_Sessions_ClaudeSessionId
    ON Sessions(ClaudeSessionId)
    WHERE ClaudeSessionId IS NOT NULL;
    PRINT 'Created unique index UX_Sessions_ClaudeSessionId';
END
ELSE
    PRINT 'Index UX_Sessions_ClaudeSessionId already exists';
GO

------------------------------------------------------------
-- 2. Add Position Tracking for Incremental Transcript Parsing
-- Eliminates O(n²) re-parsing by tracking last parsed position
------------------------------------------------------------
IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('Sessions') AND name = 'LastTranscriptPosition'
)
BEGIN
    ALTER TABLE Sessions ADD LastTranscriptPosition BIGINT DEFAULT 0;
    PRINT 'Added Sessions.LastTranscriptPosition column';
END
ELSE
    PRINT 'Sessions.LastTranscriptPosition already exists';
GO

------------------------------------------------------------
-- 3. Fix TokenUsage FK (MessageId always NULL)
-- Drop the broken FK and column - rely on MessageUuid for correlation
------------------------------------------------------------
IF EXISTS (
    SELECT 1 FROM sys.foreign_keys
    WHERE name LIKE 'FK%TokenUsag%Messa%' AND parent_object_id = OBJECT_ID('TokenUsage')
)
BEGIN
    DECLARE @fk_name NVARCHAR(256);
    SELECT @fk_name = name FROM sys.foreign_keys
    WHERE parent_object_id = OBJECT_ID('TokenUsage')
    AND name LIKE 'FK%TokenUsag%Messa%';

    EXEC('ALTER TABLE TokenUsage DROP CONSTRAINT ' + @fk_name);
    PRINT 'Dropped TokenUsage.MessageId FK constraint';
END
ELSE
    PRINT 'TokenUsage.MessageId FK already dropped';
GO

IF EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('TokenUsage') AND name = 'MessageId'
)
BEGIN
    ALTER TABLE TokenUsage DROP COLUMN MessageId;
    PRINT 'Dropped TokenUsage.MessageId column';
END
ELSE
    PRINT 'TokenUsage.MessageId already dropped';
GO

------------------------------------------------------------
-- 4. Link Messages to Events
-- Add TriggerEventId to track which event caused message logging
------------------------------------------------------------
IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('Messages') AND name = 'TriggerEventId'
)
BEGIN
    ALTER TABLE Messages ADD TriggerEventId BIGINT NULL;
    PRINT 'Added Messages.TriggerEventId column';
END
ELSE
    PRINT 'Messages.TriggerEventId already exists';
GO

-- Add FK constraint
IF NOT EXISTS (
    SELECT 1 FROM sys.foreign_keys
    WHERE name = 'FK_Messages_TriggerEvent' AND parent_object_id = OBJECT_ID('Messages')
)
BEGIN
    ALTER TABLE Messages
    ADD CONSTRAINT FK_Messages_TriggerEvent
    FOREIGN KEY (TriggerEventId) REFERENCES HookEvents(EventId);
    PRINT 'Added FK_Messages_TriggerEvent constraint';
END
ELSE
    PRINT 'FK_Messages_TriggerEvent already exists';
GO

------------------------------------------------------------
-- 5. Remove Redundant TranscriptPath from StopEvents
-- Already stored in HookEvents.TranscriptPath
------------------------------------------------------------
IF EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('StopEvents') AND name = 'TranscriptPath'
)
BEGIN
    ALTER TABLE StopEvents DROP COLUMN TranscriptPath;
    PRINT 'Dropped StopEvents.TranscriptPath (redundant)';
END
ELSE
    PRINT 'StopEvents.TranscriptPath already dropped';
GO

------------------------------------------------------------
-- 6. Replace EAV Pattern with JSON Column
-- Add ToolInputJson, migrate data, drop ToolParameters table
------------------------------------------------------------

-- Step 6a: Add JSON column
IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('ToolInvocations') AND name = 'ToolInputJson'
)
BEGIN
    ALTER TABLE ToolInvocations ADD ToolInputJson NVARCHAR(MAX) NULL;
    PRINT 'Added ToolInvocations.ToolInputJson column';
END
ELSE
    PRINT 'ToolInvocations.ToolInputJson already exists';
GO

-- Step 6b: Migrate existing ToolParameters data to JSON
-- Format: {"param1":"value1","param2":"value2",...}
IF EXISTS (SELECT 1 FROM sys.tables WHERE name = 'ToolParameters')
BEGIN
    PRINT 'Migrating ToolParameters to ToolInputJson...';

    UPDATE ti
    SET ToolInputJson = (
        SELECT tp.ParamName AS [key], tp.ParamValue AS [value]
        FROM ToolParameters tp
        WHERE tp.InvocationId = ti.InvocationId
        FOR JSON PATH
    )
    FROM ToolInvocations ti
    WHERE ti.ToolInputJson IS NULL
    AND EXISTS (SELECT 1 FROM ToolParameters WHERE InvocationId = ti.InvocationId);

    PRINT 'Migrated ' + CAST(@@ROWCOUNT AS VARCHAR) + ' tool invocations to JSON format';
END
GO

-- Step 6c: Drop ToolParameters FK first
IF EXISTS (
    SELECT 1 FROM sys.foreign_keys
    WHERE parent_object_id = OBJECT_ID('ToolParameters')
)
BEGIN
    DECLARE @tp_fk_name NVARCHAR(256);
    SELECT @tp_fk_name = name FROM sys.foreign_keys
    WHERE parent_object_id = OBJECT_ID('ToolParameters');

    EXEC('ALTER TABLE ToolParameters DROP CONSTRAINT ' + @tp_fk_name);
    PRINT 'Dropped ToolParameters FK constraint';
END
GO

-- Step 6d: Drop ToolParameters table
IF EXISTS (SELECT 1 FROM sys.tables WHERE name = 'ToolParameters')
BEGIN
    DROP TABLE ToolParameters;
    PRINT 'Dropped ToolParameters table (EAV replaced by JSON)';
END
ELSE
    PRINT 'ToolParameters table already dropped';
GO

------------------------------------------------------------
-- 7. Add Composite Indexes for Performance
------------------------------------------------------------
IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID('ToolInvocations') AND name = 'IX_ToolInvocations_SessionTool'
)
BEGIN
    CREATE INDEX IX_ToolInvocations_SessionTool
    ON ToolInvocations(EventId, ToolName);
    PRINT 'Created index IX_ToolInvocations_SessionTool';
END
ELSE
    PRINT 'Index IX_ToolInvocations_SessionTool already exists';
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID('Messages') AND name = 'IX_Messages_SessionTime'
)
BEGIN
    CREATE INDEX IX_Messages_SessionTime
    ON Messages(SessionId, Timestamp);
    PRINT 'Created index IX_Messages_SessionTime';
END
ELSE
    PRINT 'Index IX_Messages_SessionTime already exists';
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID('HookEvents') AND name = 'IX_HookEvents_SessionTime'
)
BEGIN
    CREATE INDEX IX_HookEvents_SessionTime
    ON HookEvents(SessionId, OccurredAt);
    PRINT 'Created index IX_HookEvents_SessionTime';
END
ELSE
    PRINT 'Index IX_HookEvents_SessionTime already exists';
GO

-- Index for tool correlation race fix
IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID('ToolInvocations') AND name = 'IX_ToolInvocations_ToolUseId'
)
BEGIN
    CREATE INDEX IX_ToolInvocations_ToolUseId
    ON ToolInvocations(ToolUseId)
    WHERE ToolUseId IS NOT NULL;
    PRINT 'Created index IX_ToolInvocations_ToolUseId';
END
ELSE
    PRINT 'Index IX_ToolInvocations_ToolUseId already exists';
GO

COMMIT TRANSACTION;
PRINT 'Migration 004_v2_schema completed successfully';
GO

------------------------------------------------------------
-- Verification Queries (run manually)
------------------------------------------------------------
/*
-- Check session identity - no duplicate ClaudeSessionIds
SELECT ClaudeSessionId, COUNT(*)
FROM Sessions
WHERE ClaudeSessionId IS NOT NULL
GROUP BY ClaudeSessionId
HAVING COUNT(*) > 1;

-- Check tool correlation - no orphaned PostToolUse updates
SELECT * FROM ToolInvocations
WHERE CompletedAt IS NOT NULL AND StartedAt IS NULL;

-- Verify JSON migration
SELECT TOP 10 InvocationId, ToolName, ToolInputJson
FROM ToolInvocations
WHERE ToolInputJson IS NOT NULL;

-- Check new columns exist
SELECT
    c.name AS ColumnName,
    t.name AS TableName
FROM sys.columns c
JOIN sys.tables t ON c.object_id = t.object_id
WHERE (t.name = 'Sessions' AND c.name IN ('ClaudeSessionId', 'LastTranscriptPosition'))
   OR (t.name = 'Messages' AND c.name = 'TriggerEventId')
   OR (t.name = 'ToolInvocations' AND c.name = 'ToolInputJson');
*/
