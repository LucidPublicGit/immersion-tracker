# Start tracker without rebuild. Add -WithPlex for bundled Tautulli.
param([switch]$WithPlex)
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot "..\.."))
if ($WithPlex) {
    docker compose --profile plex up -d
} else {
    docker compose up -d immersion-tracker
}
Write-Host "Started. http://127.0.0.1:8000" -ForegroundColor Green
