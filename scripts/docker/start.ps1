# Start (or create) the stack without rebuild
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot "..\.."))
docker compose up -d
Write-Host "Started. http://127.0.0.1:8000" -ForegroundColor Green
