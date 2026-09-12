# Open the immersion-tracker UI in the default browser.
# Usage:
#   .\scripts\open-ui.ps1
#   .\scripts\open-ui.ps1 queue
#   .\scripts\open-ui.ps1 docs
#   .\scripts\open-ui.ps1 api/health

$ErrorActionPreference = "Stop"

$Base = "http://127.0.0.1:8000"
$Path = if ($args.Count -gt 0) { ($args -join "/").TrimStart("/") } else { "" }
$Url = if ($Path) { "$Base/$Path" } else { "$Base/" }

Start-Process $Url
Write-Host "Opened $Url" -ForegroundColor Green
