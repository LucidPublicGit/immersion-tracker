# Stop containers (keeps data volumes / host folders)
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot "..\.."))
docker compose down
Write-Host "Stopped." -ForegroundColor Green
