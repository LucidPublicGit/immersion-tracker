# First-time Docker setup for Immersion Tracker (Windows)
# Run from repo root:  .\setup.ps1
# Or:                   .\scripts\docker\setup.ps1
param(
    [switch]$NoBrowser,
    [switch]$WithPlex,  # also start bundled Tautulli (profile: plex)
    [switch]$Wizard,    # run feature wizard after health OK
    [switch]$NoWizard   # skip end prompt for wizard
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

function Test-Cmd([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function New-WebhookSecret {
    $bytes = New-Object byte[] 24
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return ([Convert]::ToBase64String($bytes) -replace '[+/=]', 'x')
}

function Get-DotEnvValue([string]$Key) {
    $path = Join-Path $Root ".env"
    if (-not (Test-Path $path)) { return $null }
    foreach ($line in Get-Content $path) {
        if ($line -match '^\s*#' -or $line -match '^\s*$') { continue }
        $i = $line.IndexOf('=')
        if ($i -le 0) { continue }
        if ($line.Substring(0, $i).Trim() -eq $Key) {
            return $line.Substring($i + 1).Trim().Trim('"').Trim("'")
        }
    }
    return $null
}

function Set-DotEnvValue([string]$Key, [string]$Value) {
    $path = Join-Path $Root ".env"
    $lines = @()
    $found = $false
    if (Test-Path $path) {
        $lines = @(Get-Content $path | ForEach-Object {
            if ($_ -match "^\s*$([regex]::Escape($Key))=") {
                $found = $true
                "$Key=$Value"
            } else { $_ }
        })
    }
    if (-not $found) { $lines += "$Key=$Value" }
    $lines | Set-Content -Path $path -Encoding utf8
}

Write-Host "== Immersion Tracker — setup ==" -ForegroundColor Cyan

# Docker installed + running? (do not assume)
if (-not (Test-Cmd "docker")) {
    Write-Host "Docker is not installed (or not on PATH)." -ForegroundColor Red
    Write-Host "Install Docker Desktop, then re-run this script:" -ForegroundColor Yellow
    Write-Host "  https://docs.docker.com/desktop/" -ForegroundColor Yellow
    exit 1
}
try {
    docker compose version 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) { throw "compose missing" }
} catch {
    Write-Host "Docker Compose is not available." -ForegroundColor Red
    Write-Host "Docker Desktop includes Compose. Details:" -ForegroundColor Yellow
    Write-Host "  https://docs.docker.com/compose/install/" -ForegroundColor Yellow
    exit 1
}
try {
    docker info 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) { throw "docker info failed" }
} catch {
    Write-Host "Docker is installed but the engine is not running." -ForegroundColor Red
    Write-Host "Start Docker Desktop, wait until it says Running, then re-run." -ForegroundColor Yellow
    Write-Host "  https://docs.docker.com/desktop/" -ForegroundColor Yellow
    exit 1
}

# Directories
foreach ($d in @("data", "data\tadoku_export", "data\gsm", "data\mpv", "config")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $Root $d) | Out-Null
}

# settings.yaml
$settings = Join-Path $Root "config\settings.yaml"
$example = Join-Path $Root "config\settings.example.yaml"
if (-not (Test-Path $settings)) {
    if (-not (Test-Path $example)) {
        Write-Host "Missing config\settings.example.yaml" -ForegroundColor Red
        exit 1
    }
    Copy-Item $example $settings
    Write-Host "Created config\settings.yaml"
} else {
    Write-Host "config\settings.yaml already exists"
}

# .env + webhook secret
$envFile = Join-Path $Root ".env"
$envExample = Join-Path $Root ".env.example"
$generatedSecret = $false
if (-not (Test-Path $envFile)) {
    if (Test-Path $envExample) {
        Copy-Item $envExample $envFile
    } else {
        "WEBHOOK_SECRET=changeme" | Set-Content -Path $envFile -Encoding utf8
    }
    Write-Host "Created .env"
}

$secret = Get-DotEnvValue "WEBHOOK_SECRET"
if ([string]::IsNullOrWhiteSpace($secret) -or $secret -eq "changeme") {
    $secret = New-WebhookSecret
    Set-DotEnvValue "WEBHOOK_SECRET" $secret
    $generatedSecret = $true
    Write-Host "Generated WEBHOOK_SECRET (saved in .env)" -ForegroundColor Green
}

# Extension cheat-sheet (gitignored under data/)
$cheat = Join-Path $Root "data\extension-connect.txt"
@"
Immersion Tracker — browser extension settings
==============================================
Server URL:      http://127.0.0.1:8000
Webhook secret:  $secret

Firefox: about:debugging#/runtime/this-firefox → Load Temporary Add-on
         → select extension\manifest.json
Chrome:  chrome://extensions → Developer mode → Load unpacked → extension\

Then open the extension popup → gear → paste URL + secret → Test server.
"@ | Set-Content -Path $cheat -Encoding utf8

Write-Host ""
Write-Host "Building and starting immersion-tracker..." -ForegroundColor Cyan
$composeArgs = @("compose", "up", "--build", "-d", "immersion-tracker")
if ($WithPlex) {
    $composeArgs = @("compose", "--profile", "plex", "up", "--build", "-d")
}
& docker @composeArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "docker compose failed (exit $LASTEXITCODE). Try: docker compose logs" -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Waiting for health..." -ForegroundColor Cyan
$ok = $false
for ($i = 0; $i -lt 45; $i++) {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 2
        if ($r.status -eq "ok") { $ok = $true; break }
    } catch {
        Start-Sleep -Seconds 1
    }
}

Write-Host ""
if ($ok) {
    Write-Host "Ready." -ForegroundColor Green
} else {
    Write-Host "Container started but health not ready yet." -ForegroundColor Yellow
    Write-Host "  .\scripts\docker\logs.ps1" -ForegroundColor Yellow
    Write-Host "  .\scripts\docker\ensure-up.ps1   # if host port flakes on Docker Desktop" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Open:" -ForegroundColor Cyan
Write-Host "  UI:     http://127.0.0.1:8000/"
Write-Host "  Queue:  http://127.0.0.1:8000/queue"
Write-Host "  Health: http://127.0.0.1:8000/api/health"
Write-Host "  Docs:   http://127.0.0.1:8000/docs"
Write-Host ""
Write-Host "Webhook secret (extension / Tautulli):" -ForegroundColor Cyan
Write-Host "  $secret"
if ($generatedSecret) {
    Write-Host "  (also in .env and data\extension-connect.txt)" -ForegroundColor DarkGray
} else {
    Write-Host "  (from existing .env; see data\extension-connect.txt)" -ForegroundColor DarkGray
}
Write-Host ""
Write-Host "Next (optional):" -ForegroundColor Cyan
Write-Host "  YouTube: load extension\ in Firefox/Chrome — details in data\extension-connect.txt"
Write-Host "  Sheets:  .\scripts\docker\sheets-init.ps1   (needs GCP key; skip if you only want local DB)"
Write-Host "  Plex:    .\setup.ps1 -WithPlex   or   docker compose --profile plex up -d"
Write-Host "  Full:    SETUP.md"
Write-Host ""
Write-Host "Daily:" -ForegroundColor Cyan
Write-Host "  .\scripts\docker\start.ps1 | stop.ps1 | status.ps1 | logs.ps1"

if ($ok -and -not $NoBrowser) {
    try { Start-Process "http://127.0.0.1:8000/queue" } catch { }
}

# Guided feature setup (Tadoku / Plex / GSM / Hoshi / …)
# Nested flow: core setup never re-enters itself. Wizard uses -SkipCore.
if ($ok -and -not $NoWizard) {
    Write-Host ""
    $wiz = Join-Path $Root "scripts\setup-wizard.ps1"
    if ($Wizard) {
        Write-Host "Core OK — starting feature wizard (-SkipCore)." -ForegroundColor Cyan
        & $wiz -SkipCore -NoBrowser:$NoBrowser
    } elseif ([Environment]::UserInteractive -and -not [Console]::IsInputRedirected) {
        Write-Host "Core OK. Optional features (Tadoku / Plex / GSM / Hoshi / …):" -ForegroundColor Cyan
        Write-Host "  .\scripts\setup-wizard.ps1" -ForegroundColor Cyan
        Write-Host "  .\scripts\setup-wizard.ps1 -Tadoku -Plex   # non-interactive flags" -ForegroundColor DarkGray
        $ans = Read-Host "Run feature wizard now? [Y/n]"
        if ($ans -notmatch '^(n|no)$') {
            & $wiz -SkipCore -NoBrowser:$NoBrowser
        }
    } else {
        Write-Host "Feature wizard: .\scripts\setup-wizard.ps1  (or .\setup.ps1 -Wizard)" -ForegroundColor Cyan
    }
}
