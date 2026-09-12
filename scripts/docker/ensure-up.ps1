# Host-side watchdog for Docker Desktop port-proxy flake.
# Symptom: container healthy, but http://127.0.0.1:8000 hangs/resets.
# Fix: recreate the published container so com.docker.backend rebinds the port.
#
#   .\scripts\docker\ensure-up.ps1
#   .\scripts\docker\ensure-up.ps1 -Register   # Task Scheduler every 5 min
#   .\scripts\docker\ensure-up.ps1 -Unregister

param(
    [switch]$Register,
    [switch]$Unregister,
    [int]$TimeoutSec = 4
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root

$TaskName = "ImmersionTracker-EnsureUp"
$HealthUrl = "http://127.0.0.1:8000/api/health"

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task '$TaskName'." -ForegroundColor Yellow
    exit 0
}

if ($Register) {
    $script = Join-Path $PSScriptRoot "ensure-up.ps1"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`""
    $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date `
        -RepetitionInterval (New-TimeSpan -Minutes 5) `
        -RepetitionDuration ([TimeSpan]::MaxValue)
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -Force | Out-Null
    Write-Host "Registered '$TaskName' (every 5 min)." -ForegroundColor Green
    exit 0
}

function Test-HostHealth {
    try {
        $r = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec $TimeoutSec
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

if (Test-HostHealth) {
    Write-Host "OK host $HealthUrl" -ForegroundColor Green
    exit 0
}

$running = (docker inspect -f "{{.State.Running}}" immersion-tracker 2>$null) -eq "true"
$healthy = (docker inspect -f "{{if .State.Health}}{{.State.Health.Status}}{{end}}" immersion-tracker 2>$null)

Write-Host "Host health failed. container running=$running health=$healthy" -ForegroundColor Yellow

if ($running -and $healthy -eq "healthy") {
    Write-Host "Docker port proxy looks stuck — force-recreate immersion-tracker..." -ForegroundColor Yellow
    docker compose up -d --force-recreate immersion-tracker | Out-Host
} else {
    Write-Host "Starting stack..." -ForegroundColor Yellow
    docker compose up -d | Out-Host
}

Start-Sleep -Seconds 3
if (Test-HostHealth) {
    Write-Host "Recovered. $HealthUrl" -ForegroundColor Green
    exit 0
}

Write-Host "Still unreachable. Try restarting Docker Desktop, then re-run this script." -ForegroundColor Red
exit 1
