# Open the immersion-tracker UI in the default browser.
# Usage:
#   .\scripts\open-ui.ps1
#   .\scripts\open-ui.ps1 queue
#   .\scripts\open-ui.ps1 docs
#   .\scripts\open-ui.ps1 api/health

$ErrorActionPreference = "Stop"

$Base = $env:IMMERSION_TRACKER_URL
if (-not $Base) {
    $localEnv = Join-Path (Split-Path $PSScriptRoot -Parent) '.env'
    if (Test-Path -LiteralPath $localEnv) {
        $setting = Get-Content -LiteralPath $localEnv | Where-Object { $_ -match '^IMMERSION_TRACKER_URL=' } | Select-Object -Last 1
        if ($setting) { $Base = ($setting -split '=', 2)[1].Trim().Trim('"', "'") }
    }
}
if (-not $Base) { $Base = $env:IMMERSION_TRACKER_URL
if (-not $Base) {
    $localEnv = Join-Path (Split-Path $PSScriptRoot -Parent) '.env'
    if (Test-Path -LiteralPath $localEnv) {
        $setting = Get-Content -LiteralPath $localEnv | Where-Object { $_ -match '^IMMERSION_TRACKER_URL=' } | Select-Object -Last 1
        if ($setting) { $Base = ($setting -split '=', 2)[1].Trim().Trim('"', "'") }
    }
}
if (-not $Base) { $Base = $env:IMMERSION_TRACKER_URL
if (-not $Base) {
    $localEnv = Join-Path (Split-Path $PSScriptRoot -Parent) '.env'
    if (Test-Path -LiteralPath $localEnv) {
        $setting = Get-Content -LiteralPath $localEnv | Where-Object { $_ -match '^IMMERSION_TRACKER_URL=' } | Select-Object -Last 1
        if ($setting) { $Base = ($setting -split '=', 2)[1].Trim().Trim('"', "'") }
    }
}
if (-not $Base) { $Base = $env:IMMERSION_TRACKER_URL
if (-not $Base) {
    $localEnv = Join-Path (Split-Path $PSScriptRoot -Parent) '.env'
    if (Test-Path -LiteralPath $localEnv) {
        $setting = Get-Content -LiteralPath $localEnv | Where-Object { $_ -match '^IMMERSION_TRACKER_URL=' } | Select-Object -Last 1
        if ($setting) { $Base = ($setting -split '=', 2)[1].Trim().Trim('"', "'") }
    }
}
if (-not $Base) { $Base = "http://127.0.0.1:8000" }
$Base = $Base.TrimEnd('/') }
$Base = $Base.TrimEnd('/') }
$Base = $Base.TrimEnd('/') }
$Base = $Base.TrimEnd('/')
$Path = if ($args.Count -gt 0) { ($args -join "/").TrimStart("/") } else { "" }
$Url = if ($Path) { "$Base/$Path" } else { "$Base/" }

Start-Process $Url
Write-Host "Opened $Url" -ForegroundColor Green
