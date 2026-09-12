#Requires -Version 5.1
<#
.SYNOPSIS
  Finish interactive setup for Steam, Spotify, Anki, mpv, asbplayer.

.DESCRIPTION
  Collects API keys / OAuth and verifies integrations against the running app.
  Run after .\setup.ps1 when you want Steam/Spotify/etc.

  Usage:
    cd immersion-tracker
    .\scripts\setup-integrations.ps1
    .\scripts\setup-integrations.ps1 -SteamApiKey "xxx" -SpotifyClientId "..." -SpotifyClientSecret "..."
#>
[CmdletBinding()]
param(
    [string]$SteamApiKey = "",
    [string]$SpotifyClientId = "",
    [string]$SpotifyClientSecret = "",
    [switch]$SkipSpotifyOAuth,
    [switch]$SkipDockerRebuild,
    [string]$TrackerUrl = "http://127.0.0.1:8000"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "  OK  $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "  !!  $msg" -ForegroundColor Yellow }

# ── .env helpers ────────────────────────────────────────────────────────────
$EnvFile = Join-Path $Root ".env"
function Get-DotEnvMap {
    $map = @{}
    if (Test-Path $EnvFile) {
        Get-Content $EnvFile | ForEach-Object {
            if ($_ -match '^\s*#' -or $_ -match '^\s*$') { return }
            $i = $_.IndexOf('=')
            if ($i -gt 0) {
                $k = $_.Substring(0, $i).Trim()
                $v = $_.Substring($i + 1).Trim().Trim('"')
                $map[$k] = $v
            }
        }
    }
    return $map
}
function Set-DotEnvValue([string]$Key, [string]$Value) {
    $lines = @()
    $found = $false
    if (Test-Path $EnvFile) {
        $lines = Get-Content $EnvFile
        $lines = $lines | ForEach-Object {
            if ($_ -match "^\s*$([regex]::Escape($Key))=") {
                $found = $true
                "$Key=$Value"
            } else { $_ }
        }
    }
    if (-not $found) { $lines += "$Key=$Value" }
    $lines | Set-Content -Encoding utf8 $EnvFile
}

$envMap = Get-DotEnvMap

# ── Steam ───────────────────────────────────────────────────────────────────
Write-Step "Steam Web API key"
if (-not $SteamApiKey) { $SteamApiKey = $envMap['STEAM_API_KEY'] }
if (-not $SteamApiKey) {
    Write-Host "  Open https://steamcommunity.com/dev/apikey (register domain: localhost)"
    Start-Process "https://steamcommunity.com/dev/apikey"
    $SteamApiKey = Read-Host "  Paste Steam Web API key (or Enter to skip)"
}
if ($SteamApiKey) {
    Set-DotEnvValue "STEAM_API_KEY" $SteamApiKey
    if (-not $SteamId) { $SteamId = $envMap['STEAM_ID'] }
    if (-not $SteamId) { $SteamId = Read-Host "  Paste SteamID64 (or Enter to skip)" }
    if ($SteamId) {
        Set-DotEnvValue "STEAM_ID" $SteamId
        Write-Ok "STEAM_API_KEY + STEAM_ID saved to .env"
    } else {
        Write-Ok "STEAM_API_KEY saved — set STEAM_ID later"
    }
} else {
    Write-Warn "Steam key skipped — poll will fail until set"
}

# ── Spotify ─────────────────────────────────────────────────────────────────
Write-Step "Spotify Developer app"
if (-not $SpotifyClientId) { $SpotifyClientId = $envMap['SPOTIFY_CLIENT_ID'] }
if (-not $SpotifyClientSecret) { $SpotifyClientSecret = $envMap['SPOTIFY_CLIENT_SECRET'] }
if (-not $SpotifyClientId -or -not $SpotifyClientSecret) {
    Write-Host "  1. Create app: https://developer.spotify.com/dashboard"
    Write-Host "  2. Redirect URI: http://127.0.0.1:8766/callback"
    Start-Process "https://developer.spotify.com/dashboard"
    if (-not $SpotifyClientId) { $SpotifyClientId = Read-Host "  Paste Client ID (or Enter to skip)" }
    if ($SpotifyClientId -and -not $SpotifyClientSecret) {
        $SpotifyClientSecret = Read-Host "  Paste Client Secret"
    }
}
if ($SpotifyClientId -and $SpotifyClientSecret) {
    Set-DotEnvValue "SPOTIFY_CLIENT_ID" $SpotifyClientId
    Set-DotEnvValue "SPOTIFY_CLIENT_SECRET" $SpotifyClientSecret
    Write-Ok "Spotify client id/secret saved to .env"
    if (-not $SkipSpotifyOAuth) {
        Write-Step "Spotify OAuth (browser login)"
        $py = Join-Path $Root ".venv\Scripts\python.exe"
        if (-not (Test-Path $py)) { $py = "python" }
        $env:SPOTIFY_CLIENT_ID = $SpotifyClientId
        $env:SPOTIFY_CLIENT_SECRET = $SpotifyClientSecret
        & $py (Join-Path $Root "scripts\spotify_oauth_setup.py")
        if ($LASTEXITCODE -eq 0 -and (Test-Path (Join-Path $Root "data\spotify-oauth-token.json"))) {
            Write-Ok "Token written to data/spotify-oauth-token.json"
        } else {
            Write-Warn "OAuth setup did not finish — re-run scripts/spotify_oauth_setup.py"
        }
    }
} else {
    Write-Warn "Spotify credentials skipped"
}

# ── AnkiConnect ─────────────────────────────────────────────────────────────
Write-Step "AnkiConnect"
try {
    $ver = Invoke-RestMethod -Method POST -Uri http://127.0.0.1:8765 `
        -ContentType 'application/json' -Body '{"action":"version","version":6}' -TimeoutSec 3
    Write-Ok "AnkiConnect responding: $($ver | ConvertTo-Json -Compress)"
} catch {
    Write-Warn "AnkiConnect not reachable. Start Anki desktop (addon 2055492159)."
    $anki = "$env:LOCALAPPDATA\Programs\Anki\anki.exe"
    if (Test-Path $anki) {
        Start-Process $anki
        Write-Host "  Launched Anki — wait for profile, then re-run this script to verify."
    }
}

# ── mpv ─────────────────────────────────────────────────────────────────────
Write-Step "mpv"
$mpvExe = "C:\Program Files\MPV Player\mpv.exe"
$lua = Join-Path $env:APPDATA "mpv\scripts\immersion-tracker.lua"
$hist = Join-Path $Root "data\mpv\immersion-tracker.jsonl"
if (Test-Path $mpvExe) { Write-Ok "mpv installed: $mpvExe" } else { Write-Warn "mpv.exe not found" }
if (Test-Path $lua) { Write-Ok "lua script: $lua" } else { Write-Warn "lua script missing" }
if (Test-Path $hist) { Write-Ok "history file: $hist" } else { Write-Warn "history file missing" }

# ── asbplayer ───────────────────────────────────────────────────────────────
Write-Step "asbplayer"
$us = Join-Path $Root "scripts\asbplayer\immersion-tracker.user.js"
if (Test-Path $us) {
    Write-Ok "Userscript: $us"
    Write-Host "  Install with Tampermonkey/Violentmonkey, then set server URL + webhook secret."
} else {
    Write-Warn "Userscript missing"
}

# ── Docker rebuild ──────────────────────────────────────────────────────────
if (-not $SkipDockerRebuild) {
    Write-Step "Docker rebuild"
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\docker\rebuild.ps1")
}

# ── Verify API ──────────────────────────────────────────────────────────────
Write-Step "Verify $TrackerUrl"
Start-Sleep -Seconds 3
function Show-Status($name, $path) {
    try {
        $s = Invoke-RestMethod "$TrackerUrl$path" -TimeoutSec 10
        $en = $s.enabled
        $extra = if ($s.configured -ne $null) { " configured=$($s.configured)" }
                 elseif ($s.connected -ne $null) { " connected=$($s.connected)" }
                 elseif ($s.message) { " $($s.message)" } else { "" }
        Write-Host ("  {0,-10} enabled={1}{2}" -f $name, $en, $extra)
    } catch {
        Write-Warn "$name status failed: $($_.Exception.Message)"
    }
}
Show-Status "steam" "/api/steam/status"
Show-Status "anki" "/api/anki/status"
Show-Status "spotify" "/api/spotify/status"
Show-Status "mpv" "/api/mpv/status"
Show-Status "asbplayer" "/api/asbplayer/status"

Write-Step "Manual sync (safe — bootstrap baselines, no huge historical dumps)"
foreach ($p in @("/api/steam/sync","/api/anki/sync","/api/spotify/sync","/api/mpv/sync")) {
    try {
        $r = Invoke-RestMethod -Method POST "$TrackerUrl$p" -TimeoutSec 60
        Write-Host ("  {0}: {1}" -f $p, ($r | ConvertTo-Json -Compress -Depth 4))
    } catch {
        Write-Warn "$p failed: $($_.Exception.Message)"
    }
}

Write-Host "`nDone. Fill any EMPTY secrets in .env and re-run this script." -ForegroundColor Cyan
