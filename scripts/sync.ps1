# Sync telemetry hooks from repo to active Claude hooks location
# Run after making changes to ensure they take effect

$RepoHooks = "$PSScriptRoot\..\hooks"
$ActiveHooks = "$env:USERPROFILE\.claude\hooks"

Write-Host "Syncing hooks from repo to active location..." -ForegroundColor Cyan
Write-Host "  From: $RepoHooks" -ForegroundColor Gray
Write-Host "  To:   $ActiveHooks" -ForegroundColor Gray

# Ensure target exists
if (-not (Test-Path $ActiveHooks)) {
    New-Item -ItemType Directory -Path $ActiveHooks -Force | Out-Null
}

# Copy all Python files
$files = Get-ChildItem "$RepoHooks\*.py"
foreach ($file in $files) {
    Copy-Item $file.FullName $ActiveHooks -Force
    Write-Host "  Copied: $($file.Name)" -ForegroundColor Green
}

Write-Host "`nSync complete. Changes take effect immediately." -ForegroundColor Cyan
