# Rebuild image and recreate container (data/ and config/ on host are kept)
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot "..\.."))
Write-Host "Rebuilding..." -ForegroundColor Cyan
docker compose up --build -d --force-recreate
Write-Host "Rebuilt and started. http://127.0.0.1:8000" -ForegroundColor Green
