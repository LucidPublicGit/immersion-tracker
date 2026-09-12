# First-time Docker setup for Immersion Tracker
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

Write-Host "== Immersion Tracker Docker setup ==" -ForegroundColor Cyan

# Directories
New-Item -ItemType Directory -Force -Path (Join-Path $Root "data") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Root "data\tadoku_export") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $Root "config") | Out-Null

# settings.yaml
$settings = Join-Path $Root "config\settings.yaml"
$example = Join-Path $Root "config\settings.example.yaml"
if (-not (Test-Path $settings)) {
    Copy-Item $example $settings
    Write-Host "Created config\settings.yaml from example"
} else {
    Write-Host "config\settings.yaml already exists"
}

# .env
$envFile = Join-Path $Root ".env"
$envExample = Join-Path $Root ".env.example"
if (-not (Test-Path $envFile)) {
    if (Test-Path $envExample) {
        Copy-Item $envExample $envFile
    } else {
        @"
WEBHOOK_SECRET=changeme
# GOOGLE_SERVICE_ACCOUNT_JSON=
"@ | Set-Content -Path $envFile -Encoding utf8
    }
    Write-Host "Created .env — edit WEBHOOK_SECRET before production use"
} else {
    Write-Host ".env already exists"
}

# Optional service account path reminder
$sa = Join-Path $Root "data\google-service-account.json"
if (-not (Test-Path $sa)) {
    Write-Host ""
    Write-Host "Google Sheets (optional):" -ForegroundColor Yellow
    Write-Host "  1. Create a Google Cloud service account + JSON key"
    Write-Host "  2. Save key as: data\google-service-account.json"
    Write-Host "  3. Run:  .\scripts\docker\sheets-init.ps1"
    Write-Host "  (Sheets live in Google Drive in the cloud — not as a local Excel file.)"
}

Write-Host ""
Write-Host "Building and starting containers..." -ForegroundColor Cyan
docker compose up --build -d

Write-Host ""
Write-Host "Waiting for health..." -ForegroundColor Cyan
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 2
        if ($r.status -eq "ok") { $ok = $true; break }
    } catch {
        Start-Sleep -Seconds 1
    }
}

if ($ok) {
    Write-Host "OK — http://127.0.0.1:8000" -ForegroundColor Green
    Write-Host "  Docs:  http://127.0.0.1:8000/docs"
    Write-Host "  Queue: http://127.0.0.1:8000/queue"
} else {
    Write-Host "Container started but health check not ready yet. Check: docker compose logs -f" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Useful scripts:" -ForegroundColor Cyan
Write-Host "  .\scripts\docker\start.ps1"
Write-Host "  .\scripts\docker\stop.ps1"
Write-Host "  .\scripts\docker\rebuild.ps1"
Write-Host "  .\scripts\docker\logs.ps1"
Write-Host "  .\scripts\docker\sheets-sync.ps1"
Write-Host "  .\scripts\docker\sheets-init.ps1"
