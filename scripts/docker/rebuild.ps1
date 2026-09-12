# Rebuild tracker image (data/ and config/ on host are kept).
# Add -WithPlex to also recreate Tautulli.
param([switch]$WithPlex)
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot "..\.."))
Write-Host "Rebuilding..." -ForegroundColor Cyan
if ($WithPlex) {
    docker compose --profile plex up --build -d --force-recreate
} else {
    docker compose up --build -d --force-recreate immersion-tracker
}
Write-Host "Rebuilt and started. http://127.0.0.1:8000" -ForegroundColor Green
