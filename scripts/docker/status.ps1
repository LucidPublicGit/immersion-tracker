# Show compose status + health + metrics snapshot
$ErrorActionPreference = "Continue"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot "..\.."))

Write-Host "== docker compose ps ==" -ForegroundColor Cyan
docker compose ps

Write-Host "`n== host health (what the browser hits) ==" -ForegroundColor Cyan
$containerHealth = docker inspect -f "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}" immersion-tracker 2>$null
try {
    Invoke-RestMethod "http://127.0.0.1:8000/api/health" | ConvertTo-Json -Compress
} catch {
    Write-Host "API not reachable from host: $_" -ForegroundColor Red
    if ($containerHealth -eq "healthy") {
        Write-Host "Container is healthy but host port is dead (Docker Desktop proxy). Run: .\scripts\docker\ensure-up.ps1" -ForegroundColor Yellow
    }
}
Write-Host "container Healthcheck: $containerHealth"

Write-Host "`n== metrics ==" -ForegroundColor Cyan
try {
    Invoke-RestMethod "http://127.0.0.1:8000/api/metrics" | ConvertTo-Json -Depth 5
} catch {
    Write-Host "(no metrics)" -ForegroundColor Yellow
}
