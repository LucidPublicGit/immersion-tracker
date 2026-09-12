# Open a shell inside the running container
$ErrorActionPreference = "Stop"
Set-Location (Resolve-Path (Join-Path $PSScriptRoot "..\.."))
docker compose exec immersion-tracker /bin/sh
