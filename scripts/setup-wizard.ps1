#Requires -Version 5.1
<#
.SYNOPSIS
  Interactive (or flagged) setup wizard — no assumed installs.

.EXAMPLE
  .\scripts\setup-wizard.ps1
  .\scripts\setup-wizard.ps1 -Tadoku -Plex -Gsm
  .\scripts\setup-wizard.ps1 -All -NoBrowser
  .\setup.ps1 -Wizard
#>
[CmdletBinding()]
param(
    [switch]$SkipCore,
    [switch]$NoBrowser,
    [switch]$NoPause,          # skip "Press Enter" (still prompts for values unless -Yes)
    [switch]$Yes,              # accept defaults / skip optional confirms where safe
    [switch]$Tadoku,
    [switch]$Plex,
    [switch]$Gsm,
    [switch]$Hoshi,
    [switch]$YouTube,
    [switch]$Sheets,
    [switch]$All,
    [string]$RegistrationId = "",
    [string]$ContestId = "",
    [string]$ContestName = "",
    [string]$GsmDataDir = "",  # folder containing gsm.db
    [string]$Timezone = "",    # IANA TZ for .env TZ=
    [string]$PlexLibraries = "" # "Anime=anime,TV Shows=show"
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$script:FlagMode = [bool]($Tadoku -or $Plex -or $Gsm -or $Hoshi -or $YouTube -or $Sheets -or $All)
if ($All) { $Tadoku = $Plex = $Gsm = $Hoshi = $YouTube = $Sheets = $true }

# ── UI ─────────────────────────────────────────────────────────────────────
function Write-Banner($t) {
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor DarkCyan
    Write-Host "  $t" -ForegroundColor Cyan
    Write-Host ("=" * 60) -ForegroundColor DarkCyan
}
function Write-Step($m) { Write-Host "`n>> $m" -ForegroundColor Cyan }
function Write-Ok($m) { Write-Host "   OK  $m" -ForegroundColor Green }
function Write-Warn($m) { Write-Host "   !!  $m" -ForegroundColor Yellow }
function Write-Info($m) { Write-Host "   $m" }
function Pause-Enter([string]$msg = "Press Enter to continue") {
    if ($NoPause -or $Yes -or $script:FlagMode) { return }
    Write-Host ""
    try { Read-Host "   $msg" | Out-Null } catch { }
}
function Ask-Yes([string]$q, [bool]$defaultYes = $true) {
    if ($Yes) { return $defaultYes }
    $hint = if ($defaultYes) { "Y/n" } else { "y/N" }
    try { $a = Read-Host "   $q [$hint]" } catch { return $defaultYes }
    if ([string]::IsNullOrWhiteSpace($a)) { return $defaultYes }
    return $a -match '^(y|yes)$'
}
function Open-Url([string]$url) {
    if ($NoBrowser) { Write-Info "Open: $url"; return }
    try { Start-Process $url } catch { Write-Info "Open: $url" }
}
function Test-Cmd([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}
function Read-Value([string]$prompt, [string]$default = "") {
    if ($default -and ($Yes -or $script:FlagMode)) { return $default }
    try {
        $a = Read-Host "   $prompt$(if ($default) { " [$default]" })"
    } catch { return $default }
    if ([string]::IsNullOrWhiteSpace($a)) { return $default }
    return $a.Trim()
}

# ── Docker / tracker ───────────────────────────────────────────────────────
function Get-DockerState {
    if (-not (Test-Cmd "docker")) { return "missing" }
    $composeOk = $false
    try { docker compose version 1>$null 2>$null; if ($LASTEXITCODE -eq 0) { $composeOk = $true } } catch { }
    if (-not $composeOk) {
        try { docker-compose version 1>$null 2>$null; if ($LASTEXITCODE -eq 0) { $composeOk = $true } } catch { }
    }
    if (-not $composeOk) { return "no_compose" }
    try { docker info 1>$null 2>$null; if ($LASTEXITCODE -ne 0) { return "not_running" } } catch { return "not_running" }
    return "ok"
}
function Show-DockerHelp([string]$State) {
    switch ($State) {
        "missing" {
            Write-Warn "Docker is not installed (or not on PATH)."
            Write-Info "  https://docs.docker.com/desktop/"
            Open-Url "https://docs.docker.com/desktop/"
        }
        "no_compose" {
            Write-Warn "Docker present but Compose missing."
            Write-Info "  https://docs.docker.com/compose/install/"
        }
        "not_running" {
            Write-Warn "Docker installed but engine not running — start Docker Desktop."
        }
    }
}
function Invoke-Compose {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$ComposeArgs)
    if ($script:DockerState -ne "ok") {
        Write-Warn "Skipping docker compose ($($script:DockerState))."
        return $false
    }
    try {
        $argv = @("compose") + @($ComposeArgs)
        & docker @argv
        if ($LASTEXITCODE -ne 0) { Write-Warn "docker compose failed (exit $LASTEXITCODE)."; return $false }
        return $true
    } catch {
        Write-Warn "docker compose error: $_"; return $false
    }
}
function Test-TrackerUp {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/health" -TimeoutSec 3
        return ($r.status -eq "ok")
    } catch { return $false }
}
function Restart-Tracker {
    if ($script:DockerState -ne "ok") {
        Write-Warn "Cannot restart tracker — Docker not ready ($($script:DockerState))."
        return $false
    }
    Write-Info "Restarting immersion-tracker..."
    if (-not (Invoke-Compose @("up", "-d", "--force-recreate", "immersion-tracker"))) { return $false }
    for ($i = 0; $i -lt 30; $i++) {
        if (Test-TrackerUp) { Write-Ok "Tracker healthy"; return $true }
        Start-Sleep -Seconds 1
    }
    Write-Warn "Health not ready — .\scripts\docker\logs.ps1 or .\scripts\docker\ensure-up.ps1"
    return $false
}
function Show-WhenDockerWorks {
    Write-Host ""
    Write-Host "   When Docker is installed and Running:" -ForegroundColor Yellow
    Write-Info "1. .\setup.ps1 -NoWizard"
    Write-Info "2. .\scripts\setup-wizard.ps1   (or re-run with the same -Tadoku/-Plex/… flags)"
    Write-Info "3. Open http://127.0.0.1:8000/queue"
}

# ── Files ──────────────────────────────────────────────────────────────────
function New-WebhookSecret {
    $bytes = New-Object byte[] 24
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return ([Convert]::ToBase64String($bytes) -replace '[+/=]', 'x')
}
function Get-DotEnvValue([string]$Key) {
    $path = Join-Path $Root ".env"
    if (-not (Test-Path $path)) { return $null }
    foreach ($line in Get-Content $path -ErrorAction SilentlyContinue) {
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
    $lines = @(); $found = $false
    if (Test-Path $path) {
        $lines = @(Get-Content $path | ForEach-Object {
            if ($_ -match "^\s*$([regex]::Escape($Key))=") { $found = $true; "$Key=$Value" } else { $_ }
        })
    }
    if (-not $found) { $lines += "$Key=$Value" }
    $lines | Set-Content -Path $path -Encoding utf8
}
function Ensure-ProjectFiles {
    foreach ($d in @("data", "data\tadoku_export", "config")) {
        New-Item -ItemType Directory -Force -Path (Join-Path $Root $d) | Out-Null
    }
    $cfg = Join-Path $Root "config\settings.yaml"
    $ex = Join-Path $Root "config\settings.example.yaml"
    if (-not (Test-Path $cfg)) {
        if (Test-Path $ex) { Copy-Item $ex $cfg; Write-Ok "Created config\settings.yaml" }
        else { Write-Warn "Missing config\settings.example.yaml" }
    }
    $envFile = Join-Path $Root ".env"
    $envEx = Join-Path $Root ".env.example"
    if (-not (Test-Path $envFile)) {
        if (Test-Path $envEx) { Copy-Item $envEx $envFile } else { "WEBHOOK_SECRET=changeme" | Set-Content $envFile -Encoding utf8 }
        Write-Ok "Created .env"
    }
    $secret = Get-DotEnvValue "WEBHOOK_SECRET"
    if ([string]::IsNullOrWhiteSpace($secret) -or $secret -eq "changeme") {
        $secret = New-WebhookSecret
        Set-DotEnvValue "WEBHOOK_SECRET" $secret
        Write-Ok "Generated WEBHOOK_SECRET"
    }
    # TZ
    $tz = $Timezone
    if (-not $tz) { $tz = Get-DotEnvValue "TZ" }
    if ([string]::IsNullOrWhiteSpace($tz) -or $tz -eq "UTC") {
        if ($Timezone) {
            Set-DotEnvValue "TZ" $Timezone
            Write-Ok "TZ=$Timezone"
            $script:NeedRestart = $true
        } elseif (-not $Yes -and -not $script:FlagMode) {
            Write-Info "Log / GSM times use container TZ (default often UTC)."
            $guess = $env:TZ
            $ans = Read-Value "IANA timezone (e.g. America/Los_Angeles; Enter skip)" $(if ($guess) { $guess } else { "" })
            if ($ans) {
                Set-DotEnvValue "TZ" $ans
                Write-Ok "TZ=$ans"
                $script:NeedRestart = $true
            }
        }
    }
    $cheat = Join-Path $Root "data\extension-connect.txt"
    @"
Server URL:      http://127.0.0.1:8000
Webhook secret:  $secret

Other PC on LAN: http://<this-pc-lan-ip>:8000  + same secret
Windows Firewall: allow inbound TCP 8000 if other devices cannot connect.
"@ | Set-Content $cheat -Encoding utf8
    return $cfg
}
function Ensure-Settings {
    $cfg = Join-Path $Root "config\settings.yaml"
    if (-not (Test-Path $cfg)) {
        $ex = Join-Path $Root "config\settings.example.yaml"
        if (Test-Path $ex) { Copy-Item $ex $cfg }
    }
    return $cfg
}
function Set-SectionKey([string]$CfgPath, [string]$Section, [string]$Key, [string]$Value) {
    if (-not (Test-Path $CfgPath)) { return $false }
    $lines = [System.Collections.Generic.List[string]]::new()
    $lines.AddRange([string[]](Get-Content $CfgPath -Encoding UTF8))
    $in = $false; $replaced = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        $line = $lines[$i]
        if ($line -match "^${Section}:\s*$") { $in = $true; continue }
        if ($in -and $line -match '^[a-zA-Z]') { $in = $false }
        if ($in -and $line -match "^(\s+)$([regex]::Escape($Key)):\s*") {
            $lines[$i] = "$($Matches[1])${Key}: $Value"; $replaced = $true; break
        }
    }
    if ($replaced) { $lines | Set-Content -Path $CfgPath -Encoding utf8 }
    return $replaced
}
function Set-TadokuContestField([string]$CfgPath, [string]$Key, [string]$Value) {
    if (-not (Test-Path $CfgPath)) { return $false }
    $lines = [System.Collections.Generic.List[string]]::new()
    $lines.AddRange([string[]](Get-Content $CfgPath -Encoding UTF8))
    $inT = $false; $inC = $false; $replaced = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        $line = $lines[$i]
        if ($line -match '^tadoku:\s*$') { $inT = $true; $inC = $false; continue }
        if ($inT -and $line -match '^[a-zA-Z]') { $inT = $false; $inC = $false }
        if ($inT -and $line -match '^\s+contest:\s*$') { $inC = $true; continue }
        if ($inC -and $line -match '^\s{0,2}[a-zA-Z]' -and $line -notmatch '^\s+contest:') {
            if ($line -match '^[a-zA-Z]' -or ($line -match '^\s{2}[a-zA-Z]' -and $line -notmatch '^\s{4}')) {
                if ($line -notmatch "^\s+$([regex]::Escape($Key)):") { $inC = $false }
            }
        }
        if ($inC -and $line -match "^(\s+)$([regex]::Escape($Key)):\s*") {
            $lines[$i] = "$($Matches[1])${Key}: `"$Value`""; $replaced = $true; break
        }
    }
    if ($replaced) { $lines | Set-Content -Path $CfgPath -Encoding utf8 }
    return $replaced
}
function Set-PlexLibraryMap([string]$CfgPath, [string]$Spec) {
    # Spec: "Anime=anime,TV Shows=show"
    if (-not $Spec -or -not (Test-Path $CfgPath)) { return $false }
    $pairs = @()
    foreach ($part in ($Spec -split ',')) {
        $part = $part.Trim()
        if (-not $part) { continue }
        $eq = $part.IndexOf('=')
        if ($eq -le 0) { Write-Warn "Bad map entry (need Name=type): $part"; continue }
        $name = $part.Substring(0, $eq).Trim()
        $type = $part.Substring($eq + 1).Trim()
        if ($name -and $type) { $pairs += [pscustomobject]@{ Name = $name; Type = $type } }
    }
    if ($pairs.Count -eq 0) { return $false }
    $lines = [System.Collections.Generic.List[string]]::new()
    $lines.AddRange([string[]](Get-Content $CfgPath -Encoding UTF8))
    $inPlex = $false; $inMap = $false; $mapIndent = "    "
    $out = [System.Collections.Generic.List[string]]::new()
    $replaced = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        $line = $lines[$i]
        if ($line -match '^plex:\s*$') { $inPlex = $true; $inMap = $false; $out.Add($line); continue }
        if ($inPlex -and $line -match '^[a-zA-Z]') { $inPlex = $false; $inMap = $false }
        if ($inPlex -and $line -match '^(\s+)library_map:\s*$') {
            $mapIndent = $Matches[1] + "  "
            $out.Add($line)
            $inMap = $true
            foreach ($p in $pairs) { $out.Add("$mapIndent$($p.Name): $($p.Type)") }
            $replaced = $true
            # skip old map entries
            while (($i + 1) -lt $lines.Count -and $lines[$i + 1] -match '^\s{4,}\S') {
                $i++
            }
            $inMap = $false
            continue
        }
        $out.Add($line)
    }
    if ($replaced) {
        $out | Set-Content -Path $CfgPath -Encoding utf8
        Write-Ok "plex.library_map updated ($($pairs.Count) libraries)"
    } else {
        Write-Warn "Could not find plex.library_map in settings.yaml"
    }
    return $replaced
}
function Get-WebhookSecret {
    $s = Get-DotEnvValue "WEBHOOK_SECRET"
    if ([string]::IsNullOrWhiteSpace($s)) { return "changeme" }
    return $s
}
function Get-LanIpHint {
    try {
        $ip = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object { $_.IPAddress -notlike '127.*' -and $_.PrefixOrigin -ne 'WellKnown' } |
            Select-Object -First 1 -ExpandProperty IPAddress
        return $ip
    } catch { return $null }
}
function Invoke-TadokuList {
    $listPs1 = Join-Path $Root "scripts\docker\tadoku-list-registrations.ps1"
    if (Test-Path $listPs1) {
        try { & $listPs1; if ($LASTEXITCODE -eq 0) { return } } catch { Write-Warn "List script: $_" }
    }
    Write-Warn "Could not list registrations automatically."
    Write-Info "Need tracker up + Queue Save login, then: .\scripts\docker\tadoku-list-registrations.ps1"
    Write-Info "Or docs\TADOKU.md"
}

# ═══════════════════════════════════════════════════════════════════════════
$script:NeedRestart = $false
$script:ConfigOnly = $false

Write-Banner "Immersion Tracker — setup wizard"
Write-Info "No assumed installs. Missing tools → links. Config-only works offline."
Write-Info "Flags: -Tadoku -Plex -Gsm -Hoshi -YouTube -Sheets -All -Yes -NoPause -NoBrowser"
Write-Info "Values: -RegistrationId … -GsmDataDir … -Timezone … -PlexLibraries 'Anime=anime,...'"
Write-Host ""

Write-Banner "Prerequisites check"
$script:DockerState = Get-DockerState
$trackerUp = Test-TrackerUp
Write-Info ("Docker:  " + $(switch ($script:DockerState) {
    "ok" { "OK" }; "missing" { "not installed" }; "no_compose" { "no Compose" }; "not_running" { "engine stopped" }; default { $script:DockerState }
}))
Write-Info ("Tracker: " + $(if ($trackerUp) { "OK :8000" } else { "not on :8000" }))

if ($script:DockerState -ne "ok") {
    Show-DockerHelp $script:DockerState
    if (-not (Ask-Yes "Continue with config / instructions only?" $true)) {
        Show-WhenDockerWorks
        exit 0
    }
    $script:ConfigOnly = $true
}

$cfg = Ensure-ProjectFiles

if (-not $trackerUp -and -not $script:ConfigOnly -and -not $SkipCore) {
    if (Ask-Yes "Start the tracker now (.\setup.ps1 — needs Docker image build)?" $(-not $script:FlagMode)) {
        $setup = Join-Path $Root "scripts\docker\setup.ps1"
        if (Test-Path $setup) {
            & $setup -NoBrowser:$NoBrowser -NoWizard
            $script:DockerState = Get-DockerState
            $trackerUp = Test-TrackerUp
        } else { Write-Warn "Missing scripts\docker\setup.ps1" }
    } else {
        $script:ConfigOnly = $true
        Write-Info "Config-only until the app runs."
    }
} elseif ($trackerUp) {
    Write-Ok "Tracker is up"
}

# Feature selection
if (-not $script:FlagMode) {
    Write-Banner "What do you want to set up?"
    Write-Info "Typical contest path: Tadoku + Plex and/or GSM and/or Hoshi"
    Write-Host ""
    $wantTadoku = Ask-Yes "Tadoku.app login + contest?" $true
    $wantPlex   = Ask-Yes "Plex / Tautulli?" $false
    $wantGsm    = Ask-Yes "GameSentenceMiner?" $false
    $wantHoshi  = Ask-Yes "Hoshi / Boox?" $false
    $wantYt     = Ask-Yes "YouTube extension?" $false
    $wantSheets = Ask-Yes "Google Sheets mirror?" $false
} else {
    $wantTadoku = [bool]$Tadoku
    $wantPlex = [bool]$Plex
    $wantGsm = [bool]$Gsm
    $wantHoshi = [bool]$Hoshi
    $wantYt = [bool]$YouTube
    $wantSheets = [bool]$Sheets
    Write-Info ("Selected: " + (@(
        $(if ($wantTadoku) { "Tadoku" }), $(if ($wantPlex) { "Plex" }), $(if ($wantGsm) { "GSM" }),
        $(if ($wantHoshi) { "Hoshi" }), $(if ($wantYt) { "YouTube" }), $(if ($wantSheets) { "Sheets" })
    ) | Where-Object { $_ }) -join ", ")
}

if (-not ($wantTadoku -or $wantPlex -or $wantGsm -or $wantHoshi -or $wantYt -or $wantSheets)) {
    Write-Ok "Nothing selected."
    exit 0
}

$cfg = Ensure-Settings

# ── Tadoku ─────────────────────────────────────────────────────────────────
if ($wantTadoku) {
    Write-Banner "Tadoku.app"
    Write-Info "Needs a tadoku.app account only — no extra local install."
    if (-not $script:FlagMode) {
        Open-Url "https://tadoku.app"
        Pause-Enter "When you have a contest on tadoku.app, press Enter"
    }
    if ($trackerUp) {
        Write-Step "Save login in Queue (username/email + password)"
        if (-not $script:FlagMode) {
            Open-Url "http://127.0.0.1:8000/queue"
            Pause-Enter "After Save login succeeds, press Enter"
        } else {
            Write-Info "Open http://127.0.0.1:8000/queue and Save login if not done."
        }
        if (-not $RegistrationId -and (Ask-Yes "List registrations now?" $(-not $script:FlagMode))) {
            Invoke-TadokuList
        }
    } else {
        Write-Warn "Tracker not running — Save login after .\setup.ps1"
    }
    $reg = if ($RegistrationId) { $RegistrationId } else { Read-Value "Paste registration_id (Enter skip)" }
    if ($reg) {
        $cid = if ($ContestId) { $ContestId } else { Read-Value "contest_id optional (Enter skip)" }
        $cname = if ($ContestName) { $ContestName } else { Read-Value "contest display name optional (Enter skip)" }
        if (Set-TadokuContestField $cfg "registration_id" $reg) { Write-Ok "registration_id saved" }
        else { Write-Warn "Edit tadoku.contest.registration_id in settings.yaml manually" }
        if ($cid) { [void](Set-TadokuContestField $cfg "contest_id" $cid) }
        if ($cname) { [void](Set-TadokuContestField $cfg "name" $cname) }
        $script:NeedRestart = $true
    }
    Write-Info "Daily: Queue → Approve (+ submit). docs\TADOKU.md"
}

# ── Plex ───────────────────────────────────────────────────────────────────
if ($wantPlex) {
    Write-Banner "Plex / Tautulli"
    Write-Info "Does not install Plex. Tautulli is optional (bundled Docker or your own)."
    $secret = Get-WebhookSecret
    $urlDocker = "http://immersion-tracker:8000/api/webhooks/tautulli?secret=$secret"
    $urlHost = "http://127.0.0.1:8000/api/webhooks/tautulli?secret=$secret"
    if (-not $script:ConfigOnly -and $script:DockerState -eq "ok") {
        if (Ask-Yes "Start bundled Tautulli (compose profile plex)?" $(-not $script:FlagMode -or $true)) {
            if (Invoke-Compose @("--profile", "plex", "up", "-d")) {
                Write-Ok "Tautulli http://127.0.0.1:8181"
                if (-not $script:FlagMode) { Open-Url "http://127.0.0.1:8181" }
            }
        }
    } else {
        Write-Warn "Docker not ready — use your own Tautulli or finish Docker later."
        Write-Info "https://tautulli.com"
    }
    $guide = Join-Path $Root "data\plex-tautulli-connect.txt"
    @"
Immersion Tracker — Tautulli webhook
====================================
Bundled Tautulli:  http://127.0.0.1:8181
Start bundled:     docker compose --profile plex up -d
                   .\setup.ps1 -WithPlex

Webhook (Tautulli in this Docker stack):
$urlDocker

Webhook (Tautulli on host PC):
$urlHost

Method: POST | Trigger: Watched
JSON body: see docs\PLEX.md

plex.library_map keys must match Plex library names exactly (case-sensitive).
"@ | Set-Content $guide -Encoding utf8
    Write-Ok "Cheat sheet: data\plex-tautulli-connect.txt"
    Write-Host "   $urlDocker" -ForegroundColor Green
    Write-Step "Tautulli → Notification Agents → Webhook → paste URL + Watched JSON"
    Pause-Enter "After webhook saved (or skip), press Enter"

    Write-Step "Library map (Plex library name = content type)"
    Write-Info "Types: anime, show, movie, …  Example: Anime=anime,TV Shows=show"
    Write-Info "Find names in Plex → Libraries (exact spelling)."
    $mapSpec = if ($PlexLibraries) { $PlexLibraries } else {
        Read-Value "Maps comma-separated (Enter keep defaults)" ""
    }
    if ($mapSpec) {
        if (Set-PlexLibraryMap $cfg $mapSpec) { $script:NeedRestart = $true }
    } elseif (-not $script:FlagMode -and (Ask-Yes "Open settings.yaml to edit library_map?" $false)) {
        try { Start-Process notepad.exe $cfg } catch { Write-Info $cfg }
        Pause-Enter "After save, press Enter"
        $script:NeedRestart = $true
    }
    Write-Info "docs\PLEX.md"
}

# ── GSM ────────────────────────────────────────────────────────────────────
if ($wantGsm) {
    Write-Banner "GameSentenceMiner"
    Write-Info "Separate app — not installed here. https://github.com/GameSentenceMiner/GameSentenceMiner"
    if (-not $script:FlagMode -and (Ask-Yes "Open GSM GitHub?" $true)) {
        Open-Url "https://github.com/GameSentenceMiner/GameSentenceMiner"
    }
    $found = $null
    if ($GsmDataDir -and (Test-Path (Join-Path $GsmDataDir "gsm.db"))) {
        $found = $GsmDataDir
    } else {
        $candidates = @()
        if ($env:APPDATA) { $candidates += (Join-Path $env:APPDATA "GameSentenceMiner") }
        if ($env:LOCALAPPDATA) { $candidates += (Join-Path $env:LOCALAPPDATA "GameSentenceMiner") }
        foreach ($dir in $candidates) {
            if ($dir -and (Test-Path (Join-Path $dir "gsm.db"))) { $found = $dir; break }
        }
        if (-not $found) {
            Write-Warn "gsm.db not found in default locations."
            $custom = if ($GsmDataDir) { $GsmDataDir } else { Read-Value "Folder containing gsm.db (Enter skip)" }
            if ($custom -and (Test-Path (Join-Path $custom "gsm.db"))) { $found = $custom }
        }
    }
    if ($found) {
        Set-DotEnvValue "GSM_DATA_DIR" $found
        Write-Ok "GSM_DATA_DIR=$found"
        [void](Set-SectionKey $cfg "gsm" "enabled" "true")
        $script:NeedRestart = $true
    } else {
        Write-Warn "Skipped GSM — install GSM, then -GsmDataDir path or re-run."
    }
}

# ── Hoshi ──────────────────────────────────────────────────────────────────
if ($wantHoshi) {
    Write-Banner "Hoshi / Boox"
    Write-Info "Device + Hoshi app required — not installed by this wizard."
    Write-Host ""
    Write-Info "Blocked without Google Drive (stock Hoshi):"
    Write-Info "  [ ] Hoshi installed on device"
    Write-Info "  [ ] Hoshi → Google account connected"
    Write-Info "  [ ] Autosync / statistics enabled"
    Write-Info "  [ ] Wi-Fi on; folder ttu-reader-data appears in Drive"
    Write-Info "  [ ] PC can read that folder (same Google OAuth OR share with Sheets SA)"
    Write-Info "ADB cannot finish Google login or read private stats on stock builds."
    $adbScript = Join-Path $Root "scripts\boox-hoshi-setup.ps1"
    if ((Test-Path $adbScript) -and -not $script:FlagMode -and (Ask-Yes "Optional ADB helper (USB debugging)?" $false)) {
        if (-not (Test-Cmd "adb")) {
            Write-Warn "adb not on PATH — https://developer.android.com/tools/releases/platform-tools"
        }
        try { & $adbScript -OpenApp } catch { Write-Warn "ADB helper: $_" }
    }
    Pause-Enter "When Drive checklist is done (or skip), press Enter"
    if (Ask-Yes "Enable hoshi poller (source=drive) in settings?" $true) {
        if (Test-Path $adbScript) {
            try { & $adbScript -EnableTracker -Source drive } catch {
                [void](Set-SectionKey $cfg "hoshi" "enabled" "true")
                [void](Set-SectionKey $cfg "hoshi" "source" "drive")
            }
        } else {
            [void](Set-SectionKey $cfg "hoshi" "enabled" "true")
            [void](Set-SectionKey $cfg "hoshi" "source" "drive")
        }
        Write-Ok "hoshi.enabled=true source=drive"
        $script:NeedRestart = $true
    }
    Write-Info "docs\HOSHI.md  docs\GOOGLE_SHEETS.md"
}

# ── YouTube ────────────────────────────────────────────────────────────────
if ($wantYt) {
    Write-Banner "YouTube extension"
    Write-Info "Browser only — no build step. Immersion YouTube profile only."
    if (-not (Test-Path (Join-Path $Root "extension\manifest.json"))) {
        Write-Warn "extension\manifest.json missing"
    }
    $secret = Get-WebhookSecret
    $lan = Get-LanIpHint
    $cheat = Join-Path $Root "data\extension-connect.txt"
    @"
Server URL (this PC):  http://127.0.0.1:8000
Server URL (LAN PC):   http://$(if ($lan) { $lan } else { "<your-lan-ip>" }):8000
Webhook secret:        $secret

Firefox: about:debugging → Load Temporary Add-on → extension\manifest.json
Chrome:  chrome://extensions → Load unpacked → extension\
Popup → gear → paste URL + secret → Test server

Firewall: allow inbound TCP 8000 on the tracker PC if other devices fail Test server.
Tracker must be running for Test server to succeed.
"@ | Set-Content $cheat -Encoding utf8
    Write-Ok "Wrote data\extension-connect.txt"
    if ($lan) { Write-Info "Guessed LAN IP: $lan (verify in ipconfig)" }
    if (-not $trackerUp) { Write-Warn "Tracker down — Test server will fail until core setup." }
    Pause-Enter "After loading extension (or skip), press Enter"
}

# ── Sheets ─────────────────────────────────────────────────────────────────
if ($wantSheets) {
    Write-Banner "Google Sheets"
    Write-Info "Optional. Wizard does not create a GCP project."
    Write-Info "SA JSON → data\google-service-account.json → .\scripts\docker\sheets-init.ps1 (needs Docker)"
    Write-Info "OAuth Desktop client → .\scripts\docker\sheets-oauth-setup.ps1"
    Write-Info "docs\GOOGLE_SHEETS.md"
    $doc = Join-Path $Root "docs\GOOGLE_SHEETS.md"
    if ((Test-Path $doc) -and -not $script:FlagMode -and (Ask-Yes "Open GOOGLE_SHEETS.md?" $true)) {
        try { Start-Process $doc } catch { Write-Info $doc }
    }
    Pause-Enter "Press Enter to continue"
}

# ── Apply ──────────────────────────────────────────────────────────────────
if ($script:NeedRestart) {
    Write-Banner "Apply changes"
    if ($script:ConfigOnly -or $script:DockerState -ne "ok") {
        Write-Warn "Config/env updated on disk; app not restarted."
        Show-WhenDockerWorks
    } else {
        if (Restart-Tracker) { $trackerUp = $true }
    }
}

if ($wantHoshi -and $trackerUp -and (Ask-Yes "Trigger Hoshi sync now?" $(-not $script:FlagMode))) {
    try {
        $r = Invoke-RestMethod -Method POST "http://127.0.0.1:8000/api/hoshi/sync" -TimeoutSec 120
        Write-Ok ($r | ConvertTo-Json -Compress)
    } catch { Write-Warn "Hoshi sync failed — finish Drive auth first." }
}
if ($wantGsm -and $trackerUp) {
    try {
        $st = Invoke-RestMethod "http://127.0.0.1:8000/api/gsm/status" -TimeoutSec 8
        Write-Ok ("GSM: " + ($st | ConvertTo-Json -Compress))
    } catch { Write-Warn "GSM status unavailable" }
}

Write-Banner "Done"
Write-Host ""
if ($trackerUp) {
    Write-Info "App:   http://127.0.0.1:8000/"
    Write-Info "Queue: http://127.0.0.1:8000/queue  ← Approve → Tadoku"
    if (-not $NoBrowser -and -not $script:FlagMode) { Open-Url "http://127.0.0.1:8000/queue" }
} else {
    Write-Warn "Tracker still not running."
    Show-WhenDockerWorks
}
Write-Info "Re-run: .\scripts\setup-wizard.ps1 [-Tadoku|-Plex|-Gsm|-Hoshi|-YouTube|-Sheets|-All]"
Write-Info "Guide: SETUP.md"
Write-Host ""
