# Force a Google Sheets sync via the running API
$ErrorActionPreference = "Stop"
$Base = if ($env:IMMERSION_URL) { $env:IMMERSION_URL.TrimEnd("/") } else { "http://127.0.0.1:8000" }

Write-Host "POST $Base/api/sync/sheets" -ForegroundColor Cyan
try {
    $r = Invoke-RestMethod -Method POST -Uri "$Base/api/sync/sheets" -ContentType "application/json"
    $r | ConvertTo-Json -Depth 6
    if ($r.logs.reason -eq "sheets_disabled" -or $r.manual.reason -eq "sheets_disabled") {
        Write-Host ""
        Write-Host "Sheets are disabled or not configured." -ForegroundColor Yellow
        Write-Host "See scripts\docker\sheets-init.ps1 and docs in README (Google Sheets section)."
    }
} catch {
    Write-Host "Sync failed: $_" -ForegroundColor Red
    Write-Host "Is the container running? .\scripts\docker\start.ps1"
    exit 1
}
