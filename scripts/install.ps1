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
    Write-Error "Python not found. Please install Python 3.8+ and ensure it's in PATH."
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

# Create database
if (-not $SkipDatabase) {
    Write-Host "`nCreating database schema..." -ForegroundColor Yellow
    $scriptPath = Join-Path $PSScriptRoot "..\migrations\001_initial_schema.sql"

    try {
        sqlcmd -S $Server -E -i $scriptPath -b
        if ($LASTEXITCODE -ne 0) {
            throw "sqlcmd failed"
        }
        Write-Host "  Database schema created" -ForegroundColor Green
    }
    catch {
        Write-Warning "Could not create database automatically."
        Write-Host "  Please run migrations/001_initial_schema.sql manually in SSMS"
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
