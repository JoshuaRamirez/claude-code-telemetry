-- Migration 005: Data Fidelity Fix
-- Fixes: unique filtered indexes on Messages.MessageUuid and TokenUsage.MessageUuid (H1),
-- ContentBlocksJson column on Messages (C1), ToolUseId column on SubagentEvents (M4).
--
-- NOTE: IGNORE_DUP_KEY is not compatible with filtered indexes in SQL Server.
-- Dedup on INSERT is handled in Python with try/except IntegrityError.
--
-- All changes are additive/non-destructive. All operations are idempotent.
-- Includes dedup of existing data before creating unique indexes.
-- Run: sqlcmd -S localhost -E -d ClaudeConversations -i migrations/005_data_fidelity.sql

SET QUOTED_IDENTIFIER ON;
SET ANSI_NULLS ON;
SET XACT_ABORT ON;
BEGIN TRANSACTION;

PRINT 'Starting migration 005_data_fidelity...';

------------------------------------------------------------
-- 1a. Deduplicate Messages before unique index (H1 prerequisite)
-- Keep the first inserted row (lowest MessageId) for each MessageUuid.
------------------------------------------------------------
PRINT 'Deduplicating Messages by MessageUuid...';

;WITH cte AS (
    SELECT MessageId,
           ROW_NUMBER() OVER (PARTITION BY MessageUuid ORDER BY MessageId) AS rn
    FROM Messages
    WHERE MessageUuid IS NOT NULL
)
DELETE FROM cte WHERE rn > 1;

PRINT 'Deleted ' + CAST(@@ROWCOUNT AS VARCHAR) + ' duplicate message rows';

-- Drop old non-unique index if it exists
IF EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID('Messages') AND name = 'IX_Messages_MessageUuid'
)
BEGIN
    DROP INDEX IX_Messages_MessageUuid ON Messages;
    PRINT 'Dropped old IX_Messages_MessageUuid index';
END

-- Create unique filtered index (NULLs excluded — system messages have NULL UUIDs)
IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID('Messages') AND name = 'UX_Messages_MessageUuid'
)
BEGIN
    CREATE UNIQUE INDEX UX_Messages_MessageUuid
    ON Messages(MessageUuid)
    WHERE MessageUuid IS NOT NULL;
    PRINT 'Created UX_Messages_MessageUuid (unique, filtered)';
END
ELSE
    PRINT 'UX_Messages_MessageUuid already exists';

------------------------------------------------------------
-- 1b. Deduplicate TokenUsage before unique index (H1 prerequisite)
-- Keep the first inserted row (lowest UsageId) for each MessageUuid.
------------------------------------------------------------
PRINT 'Deduplicating TokenUsage by MessageUuid...';

;WITH cte AS (
    SELECT UsageId,
           ROW_NUMBER() OVER (PARTITION BY MessageUuid ORDER BY UsageId) AS rn
    FROM TokenUsage
    WHERE MessageUuid IS NOT NULL
)
DELETE FROM cte WHERE rn > 1;

PRINT 'Deleted ' + CAST(@@ROWCOUNT AS VARCHAR) + ' duplicate token usage rows';

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE object_id = OBJECT_ID('TokenUsage') AND name = 'UX_TokenUsage_MessageUuid'
)
BEGIN
    CREATE UNIQUE INDEX UX_TokenUsage_MessageUuid
    ON TokenUsage(MessageUuid)
    WHERE MessageUuid IS NOT NULL;
    PRINT 'Created UX_TokenUsage_MessageUuid (unique, filtered)';
END
ELSE
    PRINT 'UX_TokenUsage_MessageUuid already exists';

------------------------------------------------------------
-- 1c. Add ContentBlocksJson column to Messages (C1)
-- Stores full message.content array as JSON for faithful
-- conversation reconstruction (text + thinking + tool_use).
------------------------------------------------------------
IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('Messages') AND name = 'ContentBlocksJson'
)
BEGIN
    ALTER TABLE Messages ADD ContentBlocksJson NVARCHAR(MAX) NULL;
    PRINT 'Added Messages.ContentBlocksJson column';
END
ELSE
    PRINT 'Messages.ContentBlocksJson already exists';

------------------------------------------------------------
-- 1d. Add ToolUseId column to SubagentEvents (M4)
-- Links subagent events to their parent Task tool invocation.
------------------------------------------------------------
IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('SubagentEvents') AND name = 'ToolUseId'
)
BEGIN
    ALTER TABLE SubagentEvents ADD ToolUseId NVARCHAR(100) NULL;
    PRINT 'Added SubagentEvents.ToolUseId column';
END
ELSE
    PRINT 'SubagentEvents.ToolUseId already exists';

COMMIT TRANSACTION;
PRINT 'Migration 005_data_fidelity completed successfully';
GO

------------------------------------------------------------
-- Verification Queries (run manually)
------------------------------------------------------------
/*
-- Check no duplicate MessageUuids remain
SELECT 'Messages' AS tbl, COUNT(*) as dup_count
FROM (SELECT MessageUuid FROM Messages WHERE MessageUuid IS NOT NULL GROUP BY MessageUuid HAVING COUNT(*) > 1) t
UNION ALL
SELECT 'TokenUsage', COUNT(*)
FROM (SELECT MessageUuid FROM TokenUsage WHERE MessageUuid IS NOT NULL GROUP BY MessageUuid HAVING COUNT(*) > 1) t2;

-- Check new indexes
SELECT name, is_unique, filter_definition
FROM sys.indexes
WHERE object_id IN (OBJECT_ID('Messages'), OBJECT_ID('TokenUsage'))
AND name LIKE 'UX_%';

-- Check new columns
SELECT t.name AS TableName, c.name AS ColumnName
FROM sys.columns c
JOIN sys.tables t ON c.object_id = t.object_id
WHERE (t.name = 'Messages' AND c.name = 'ContentBlocksJson')
   OR (t.name = 'SubagentEvents' AND c.name = 'ToolUseId');
*/
