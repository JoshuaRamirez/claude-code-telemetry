# Claude Code Telemetry - Windows Installation Script

param(
    [string]$Server = "localhost",
    [string]$Database = "ClaudeConversations",
    [switch]$SkipDatabase
)

$ErrorActionPreference = "Stop"

Write-Host "Claude Code Telemetry - Installation" -ForegroundColor Cyan
Write-Host "====================================" -ForegroundColor Cyan

# Check Python
Write-Host "`nChecking Python..." -ForegroundColor Yellow
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Error "Python not found. Please install Python 3.9+ and ensure it's in PATH."
    exit 1
}
$pythonVersion = python --version
Write-Host "  Found: $pythonVersion" -ForegroundColor Green

# Check pyodbc
Write-Host "`nChecking pyodbc..." -ForegroundColor Yellow
$pyodbcCheck = python -c "import pyodbc; print(pyodbc.version)" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Installing pyodbc..." -ForegroundColor Yellow
    pip install pyodbc
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to install pyodbc"
        exit 1
    }
}
Write-Host "  pyodbc OK" -ForegroundColor Green

# Check ODBC Driver
Write-Host "`nChecking ODBC Driver 17..." -ForegroundColor Yellow
$driver = Get-OdbcDriver | Where-Object { $_.Name -like "*ODBC Driver 17*" }
if (-not $driver) {
    Write-Warning "ODBC Driver 17 for SQL Server not found."
    Write-Host "  Download from: https://docs.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server"
    exit 1
}
Write-Host "  Found: $($driver.Name)" -ForegroundColor Green

# Run all migrations
if (-not $SkipDatabase) {
    Write-Host "`nRunning database migrations..." -ForegroundColor Yellow
    $migrationsDir = Join-Path $PSScriptRoot "..\migrations"
    $migrations = Get-ChildItem -Path $migrationsDir -Filter "*.sql" | Sort-Object Name

    if ($migrations.Count -eq 0) {
        Write-Warning "No migration files found in $migrationsDir"
    }
    else {
        $failed = $false
        foreach ($migration in $migrations) {
            Write-Host "  Running $($migration.Name)..." -NoNewline
            try {
                sqlcmd -S $Server -E -i $migration.FullName -b
                if ($LASTEXITCODE -ne 0) {
                    throw "sqlcmd failed"
                }
                Write-Host " OK" -ForegroundColor Green
            }
            catch {
                Write-Host " FAILED" -ForegroundColor Red
                $failed = $true
                break
            }
        }
        if ($failed) {
            Write-Warning "Migration failed. Please run the remaining migrations manually in SSMS."
        }
        else {
            Write-Host "  All $($migrations.Count) migrations applied" -ForegroundColor Green
        }
    }
}

# Set environment variable
Write-Host "`nSetting environment variable..." -ForegroundColor Yellow
$connString = "Driver={ODBC Driver 17 for SQL Server};Server=$Server;Database=$Database;Trusted_Connection=yes;"
[Environment]::SetEnvironmentVariable("CLAUDE_TELEMETRY_CONNECTION", $connString, "User")
Write-Host "  CLAUDE_TELEMETRY_CONNECTION set for current user" -ForegroundColor Green

# Done
Write-Host "`n====================================" -ForegroundColor Cyan
Write-Host "Installation complete!" -ForegroundColor Green
Write-Host "`nNext steps:" -ForegroundColor Yellow
Write-Host "  1. Restart your terminal to pick up environment variable"
Write-Host "  2. Install plugin: /plugin install $PSScriptRoot\.."
Write-Host "  3. Start a new Claude session - telemetry will begin automatically"
