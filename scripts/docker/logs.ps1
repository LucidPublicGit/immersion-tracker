# Follow container logs
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot "..\.."))
docker compose logs -f immersion-tracker
