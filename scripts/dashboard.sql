-- Productivity Dashboard for Claude Code Telemetry
-- Usage: EXEC sp_ProductivityDashboard @Days = 7;

IF OBJECT_ID('vw_ProductivityDashboard', 'V') IS NOT NULL
    DROP VIEW vw_ProductivityDashboard;
GO

CREATE VIEW vw_ProductivityDashboard AS
WITH DateRange AS (
    SELECT
        DATEADD(DAY, -7, GETUTCDATE()) AS StartDate,
        GETUTCDATE() AS EndDate
),
DailyStats AS (
    SELECT
        CAST(OccurredAt AS DATE) AS Day,
        COUNT(CASE WHEN EventName = 'UserPromptSubmit' THEN 1 END) AS Prompts,
        COUNT(CASE WHEN EventName = 'PreToolUse' THEN 1 END) AS Tools,
        COUNT(DISTINCT ClaudeSessionId) AS Sessions
    FROM HookEvents, DateRange
    WHERE OccurredAt > StartDate
      AND ClaudeSessionId IN (SELECT ClaudeSessionId FROM HookEvents GROUP BY ClaudeSessionId HAVING COUNT(*) > 10)
    GROUP BY CAST(OccurredAt AS DATE)
),
SessionStats AS (
    SELECT
        ClaudeSessionId,
        COUNT(CASE WHEN EventName = 'UserPromptSubmit' THEN 1 END) AS Prompts,
        COUNT(CASE WHEN EventName = 'PreToolUse' THEN 1 END) AS Tools,
        DATEDIFF(MINUTE, MIN(OccurredAt), MAX(OccurredAt)) AS DurationMin
    FROM HookEvents, DateRange
    WHERE OccurredAt > StartDate
    GROUP BY ClaudeSessionId
    HAVING COUNT(*) > 10
),
HourlyStats AS (
    SELECT
        DATEPART(HOUR, DATEADD(HOUR, -6, OccurredAt)) AS HourCT,
        COUNT(*) AS ToolCalls
    FROM HookEvents, DateRange
    WHERE OccurredAt > StartDate AND EventName = 'PreToolUse'
    GROUP BY DATEPART(HOUR, DATEADD(HOUR, -6, OccurredAt))
)
SELECT
    'Summary' AS Section,
    'Total Prompts (7d)' AS Metric,
    CAST(SUM(Prompts) AS VARCHAR) AS Value
FROM DailyStats
UNION ALL
SELECT 'Summary', 'Total Tools (7d)', CAST(SUM(Tools) AS VARCHAR) FROM DailyStats
UNION ALL
SELECT 'Summary', 'Avg Tools/Prompt', CAST(CAST(1.0 * SUM(Tools) / NULLIF(SUM(Prompts), 0) AS DECIMAL(5,1)) AS VARCHAR) FROM DailyStats
UNION ALL
SELECT 'Summary', 'Active Sessions', CAST(COUNT(*) AS VARCHAR) FROM SessionStats
UNION ALL
SELECT 'Summary', 'Avg Session Length', CAST(AVG(DurationMin) AS VARCHAR) + ' min' FROM SessionStats
UNION ALL
SELECT 'Peak', 'Peak Hour (CT)', CAST(HourCT AS VARCHAR) + ':00' FROM HourlyStats WHERE ToolCalls = (SELECT MAX(ToolCalls) FROM HourlyStats)
UNION ALL
SELECT 'Peak', 'Peak Day', CAST(Day AS VARCHAR) FROM DailyStats WHERE Tools = (SELECT MAX(Tools) FROM DailyStats);
GO

-- Comprehensive dashboard stored procedure
IF OBJECT_ID('sp_ProductivityDashboard', 'P') IS NOT NULL
    DROP PROCEDURE sp_ProductivityDashboard;
GO

CREATE PROCEDURE sp_ProductivityDashboard
    @Days INT = 7
AS
BEGIN
    SET NOCOUNT ON;
    DECLARE @StartDate DATETIME = DATEADD(DAY, -@Days, GETUTCDATE());

    -- Section 1: Overview
    PRINT '=== PRODUCTIVITY DASHBOARD (Last ' + CAST(@Days AS VARCHAR) + ' Days) ===';
    PRINT '';

    SELECT
        'OVERVIEW' AS Section,
        COUNT(CASE WHEN EventName = 'UserPromptSubmit' THEN 1 END) AS TotalPrompts,
        COUNT(CASE WHEN EventName = 'PreToolUse' THEN 1 END) AS TotalTools,
        CAST(1.0 * COUNT(CASE WHEN EventName = 'PreToolUse' THEN 1 END) /
             NULLIF(COUNT(CASE WHEN EventName = 'UserPromptSubmit' THEN 1 END), 0) AS DECIMAL(5,1)) AS ToolsPerPrompt,
        COUNT(DISTINCT ClaudeSessionId) AS UniqueSessions,
        COUNT(DISTINCT Cwd) AS UniqueProjects
    FROM HookEvents
    WHERE OccurredAt > @StartDate
      AND ClaudeSessionId IN (SELECT ClaudeSessionId FROM HookEvents GROUP BY ClaudeSessionId HAVING COUNT(*) > 10);

    -- Section 2: Daily Trend
    SELECT
        'DAILY_TREND' AS Section,
        CAST(OccurredAt AS DATE) AS Day,
        COUNT(CASE WHEN EventName = 'UserPromptSubmit' THEN 1 END) AS Prompts,
        COUNT(CASE WHEN EventName = 'PreToolUse' THEN 1 END) AS Tools,
        CAST(1.0 * COUNT(CASE WHEN EventName = 'PreToolUse' THEN 1 END) /
             NULLIF(COUNT(CASE WHEN EventName = 'UserPromptSubmit' THEN 1 END), 0) AS DECIMAL(5,1)) AS Efficiency
    FROM HookEvents
    WHERE OccurredAt > @StartDate
      AND ClaudeSessionId IN (SELECT ClaudeSessionId FROM HookEvents GROUP BY ClaudeSessionId HAVING COUNT(*) > 10)
    GROUP BY CAST(OccurredAt AS DATE)
    ORDER BY CAST(OccurredAt AS DATE);

    -- Section 3: Hourly Pattern (Central Time - adjust HOUR offset for your timezone)
    SELECT
        'HOURLY_PATTERN' AS Section,
        DATEPART(HOUR, DATEADD(HOUR, -6, OccurredAt)) AS HourCT,
        COUNT(CASE WHEN EventName = 'UserPromptSubmit' THEN 1 END) AS Prompts,
        COUNT(CASE WHEN EventName = 'PreToolUse' THEN 1 END) AS Tools
    FROM HookEvents
    WHERE OccurredAt > @StartDate
      AND ClaudeSessionId IN (SELECT ClaudeSessionId FROM HookEvents GROUP BY ClaudeSessionId HAVING COUNT(*) > 10)
    GROUP BY DATEPART(HOUR, DATEADD(HOUR, -6, OccurredAt))
    ORDER BY DATEPART(HOUR, DATEADD(HOUR, -6, OccurredAt));

    -- Section 4: Top Tools
    SELECT TOP 10
        'TOP_TOOLS' AS Section,
        ToolName,
        COUNT(*) AS Calls,
        AVG(DurationMs) AS AvgMs
    FROM ToolInvocations
    WHERE StartedAt > @StartDate
    GROUP BY ToolName
    ORDER BY COUNT(*) DESC;

    -- Section 5: Project Activity
    SELECT TOP 10
        'PROJECT_ACTIVITY' AS Section,
        RIGHT(Cwd, 40) AS Project,
        COUNT(CASE WHEN EventName = 'UserPromptSubmit' THEN 1 END) AS Prompts,
        COUNT(CASE WHEN EventName = 'PreToolUse' THEN 1 END) AS Tools
    FROM HookEvents
    WHERE OccurredAt > @StartDate AND Cwd IS NOT NULL
    GROUP BY Cwd
    ORDER BY COUNT(*) DESC;

    -- Section 6: Session Archetypes
    SELECT
        'SESSION_TYPES' AS Section,
        CASE
            WHEN 1.0 * ReadCalls / NULLIF(TotalTools, 0) > 0.5 THEN 'Explorer'
            WHEN 1.0 * EditCalls / NULLIF(TotalTools, 0) > 0.3 THEN 'Editor'
            WHEN 1.0 * BashCalls / NULLIF(TotalTools, 0) > 0.4 THEN 'Scripter'
            WHEN 1.0 * TaskCalls / NULLIF(TotalTools, 0) > 0.1 THEN 'Delegator'
            ELSE 'Balanced'
        END AS SessionType,
        COUNT(*) AS Sessions,
        AVG(TotalTools) AS AvgTools
    FROM (
        SELECT
            h.ClaudeSessionId,
            SUM(CASE WHEN t.ToolName = 'Read' THEN 1 ELSE 0 END) AS ReadCalls,
            SUM(CASE WHEN t.ToolName IN ('Edit', 'Write') THEN 1 ELSE 0 END) AS EditCalls,
            SUM(CASE WHEN t.ToolName = 'Bash' THEN 1 ELSE 0 END) AS BashCalls,
            SUM(CASE WHEN t.ToolName = 'Task' THEN 1 ELSE 0 END) AS TaskCalls,
            COUNT(*) AS TotalTools
        FROM HookEvents h
        JOIN ToolInvocations t ON h.EventId = t.EventId
        WHERE h.OccurredAt > @StartDate
        GROUP BY h.ClaudeSessionId
        HAVING COUNT(*) > 20
    ) x
    GROUP BY CASE
            WHEN 1.0 * ReadCalls / NULLIF(TotalTools, 0) > 0.5 THEN 'Explorer'
            WHEN 1.0 * EditCalls / NULLIF(TotalTools, 0) > 0.3 THEN 'Editor'
            WHEN 1.0 * BashCalls / NULLIF(TotalTools, 0) > 0.4 THEN 'Scripter'
            WHEN 1.0 * TaskCalls / NULLIF(TotalTools, 0) > 0.1 THEN 'Delegator'
            ELSE 'Balanced'
        END;

    -- Section 7: Tool Workflows (common sequences)
    ;WITH ToolSeq AS (
        SELECT
            ToolName,
            LAG(ToolName, 1) OVER (ORDER BY InvocationId) AS PrevTool
        FROM ToolInvocations
        WHERE StartedAt > @StartDate
    )
    SELECT TOP 10
        'WORKFLOWS' AS Section,
        PrevTool + ' -> ' + ToolName AS Sequence,
        COUNT(*) AS Occurrences
    FROM ToolSeq
    WHERE PrevTool IS NOT NULL AND PrevTool != ToolName
    GROUP BY PrevTool, ToolName
    ORDER BY COUNT(*) DESC;
END;
GO

PRINT 'Dashboard objects created. Run: EXEC sp_ProductivityDashboard @Days = 7;';
