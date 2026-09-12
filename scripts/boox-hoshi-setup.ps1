# Boox + Hoshi Reader setup via ADB (device prep, not live progress polling).
#
# Progress auto-logging still uses Google Drive → immersion-tracker (see docs/HOSHI.md).
# ADB cannot complete Hoshi's Google OAuth UI or flip in-app toggles that live in private storage.
#
# Usage:
#   .\scripts\boox-hoshi-setup.ps1
#   .\scripts\boox-hoshi-setup.ps1 -InstallHoshi -OpenApp
#   .\scripts\boox-hoshi-setup.ps1 -EnableTracker -Source drive
#   .\scripts\boox-hoshi-setup.ps1 -WirelessConnect "192.168.1.50:5555"

param(
    [string]$Serial = "",
    [string]$Connect = "",
    [switch]$InstallHoshi,
    [switch]$OpenApp,
    [switch]$EnableTracker,
    [ValidateSet("drive", "adb", "auto")]
    [string]$Source = "drive",
    [switch]$SkipAdbInstall,
    [switch]$StatusOnly
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$Package = "moe.antimony.hoshi"
$HoshiRepo = "HuangAntimony/Hoshi-Reader-Android"

function Write-Step([string]$msg) { Write-Host ""; Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg) { Write-Host "  OK  $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "  !!  $msg" -ForegroundColor Yellow }
function Write-Info([string]$msg) { Write-Host "      $msg" }

function Get-AdbPath {
    $candidates = @(
        (Join-Path $Root "tools\platform-tools\adb.exe"),
        "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
    )
    foreach ($c in $candidates) {
        if ($c -and (Test-Path $c)) { return (Resolve-Path $c).Path }
    }
    $cmd = Get-Command adb -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Invoke-Adb {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$AdbArgs)
    $all = @()
    if ($Serial) { $all += @("-s", $Serial) }
    $all += $AdbArgs
    & $script:Adb @all
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne $null) {
        # Many adb shell probes return non-zero; callers decide
    }
}

# --- 1) adb binary ---
Write-Step "Locate adb"
$script:Adb = Get-AdbPath
if (-not $script:Adb -and -not $SkipAdbInstall) {
    Write-Info "Installing platform-tools..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\install-platform-tools.ps1")
    $script:Adb = Get-AdbPath
}
if (-not $script:Adb) { throw "adb not found. Run scripts\install-platform-tools.ps1" }
Write-Ok $script:Adb

# --- 2) device ---
Write-Step "Device"
if ($Connect) {
    Write-Info "adb connect $Connect"
    & $script:Adb connect $Connect | Out-Host
}
$devicesOut = & $script:Adb devices
$online = @()
foreach ($line in ($devicesOut -split "`n")) {
    $t = $line.Trim()
    if (-not $t -or $t.StartsWith("List of devices")) { continue }
    $parts = $t -split "\s+"
    if ($parts.Count -ge 2 -and $parts[1] -eq "device") { $online += $parts[0] }
}
if ($online.Count -eq 0) {
    throw "No ADB device online. Plug in Boox, enable USB debugging, accept the RSA prompt."
}
if ($Serial -and ($online -notcontains $Serial)) {
    throw "Serial $Serial not online. Online: $($online -join ', ')"
}
if (-not $Serial -and $online.Count -gt 1) {
    Write-Warn "Multiple devices: $($online -join ', '). Using first; pass -Serial to pin."
}
if (-not $Serial) { $Serial = $online[0] }
$model = (& $script:Adb -s $Serial shell getprop ro.product.model).Trim()
$android = (& $script:Adb -s $Serial shell getprop ro.build.version.release).Trim()
Write-Ok "serial=$Serial model=$model android=$android"

if ($StatusOnly) {
    Write-Step "Hoshi package status"
    $path = (& $script:Adb -s $Serial shell pm path $Package 2>$null)
    if ($path -match "package:") {
        Write-Ok "Installed: $path"
        & $script:Adb -s $Serial shell dumpsys package $Package 2>$null |
            Select-String -Pattern "versionName|versionCode" |
            Select-Object -First 6 | ForEach-Object { Write-Info $_.Line.Trim() }
    } else {
        Write-Warn "Hoshi not installed ($Package)"
    }
    Write-Step "immersion-tracker Hoshi config"
    $cfg = Join-Path $Root "config\settings.yaml"
    if (Test-Path $cfg) {
        Select-String -Path $cfg -Pattern "^\s*(enabled|source|package|root_folder)" |
            Select-Object -First 20 | ForEach-Object { Write-Info $_.Line.Trim() }
    }
    exit 0
}

# --- 3) optional Hoshi install/update ---
if ($InstallHoshi) {
    Write-Step "Install / update Hoshi Reader from GitHub"
    $abiLine = (& $script:Adb -s $Serial shell getprop ro.product.cpu.abi).Trim()
    $asset = if ($abiLine -match "arm64") {
        "Hoshi-Reader-*-arm64-v8a.apk"
    } else {
        "Hoshi-Reader-*-armeabi-v7a.apk"
    }
    Write-Info "device abi=$abiLine → prefer $asset"

    $dlDir = Join-Path $Root "tools\apks"
    New-Item -ItemType Directory -Force -Path $dlDir | Out-Null

    $release = gh api "repos/$HoshiRepo/releases/latest" | ConvertFrom-Json
    $apkAsset = $release.assets | Where-Object {
        $_.name -like "*.apk" -and (
            ($abiLine -match "arm64" -and $_.name -match "arm64") -or
            ($abiLine -notmatch "arm64" -and $_.name -match "armeabi")
        )
    } | Select-Object -First 1
    if (-not $apkAsset) {
        $apkAsset = $release.assets | Where-Object { $_.name -like "*.apk" } | Select-Object -First 1
    }
    if (-not $apkAsset) { throw "No APK on latest release $($release.tag_name)" }

    $apkPath = Join-Path $dlDir $apkAsset.name
    if (-not (Test-Path $apkPath)) {
        Write-Info "Downloading $($apkAsset.name) ..."
        Invoke-WebRequest -Uri $apkAsset.browser_download_url -OutFile $apkPath
    } else {
        Write-Info "Using cached $apkPath"
    }
    Write-Info "adb install -r ..."
    & $script:Adb -s $Serial install -r $apkPath | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "adb install failed" }
    Write-Ok "Hoshi $($release.tag_name) installed"
} else {
    Write-Step "Hoshi package check"
    $path = (& $script:Adb -s $Serial shell pm path $Package 2>$null)
    if ($path -match "package:") {
        Write-Ok "Already installed"
        Write-Info $path.Trim()
    } else {
        Write-Warn "Not installed. Re-run with -InstallHoshi"
    }
}

# --- 4) permissions we can grant via ADB ---
Write-Step "Grant permissions (where allowed)"
$grants = @(
    "android.permission.INTERNET",
    "android.permission.ACCESS_NETWORK_STATE",
    "android.permission.WAKE_LOCK",
    "android.permission.FOREGROUND_SERVICE",
    "android.permission.POST_NOTIFICATIONS"
)
foreach ($perm in $grants) {
    $out = ""
    try {
        $out = & $script:Adb -s $Serial shell pm grant $Package $perm 2>&1 | Out-String
    } catch {
        $out = "$_"
    }
    if ($out -match "Exception|Unknown|not held|SecurityException|does not") {
        Write-Info "skip $perm"
    } elseif ($LASTEXITCODE -eq 0 -or -not $out.Trim()) {
        Write-Ok $perm
    } else {
        Write-Info "skip $perm ($($out.Trim()))"
    }
}

# Keep screen on while charging (helps first-time Drive sync)
try {
    & $script:Adb -s $Serial shell settings put global stay_on_while_plugged_in 3 2>&1 | Out-Null
    Write-Ok "stay_on_while_plugged_in=3 (while charging)"
} catch {
    Write-Info "could not set stay_on_while_plugged_in"
}

# --- 5) open app ---
if ($OpenApp -or $InstallHoshi) {
    Write-Step "Launch Hoshi"
    try {
        & $script:Adb -s $Serial shell am start -a android.intent.action.MAIN -c android.intent.category.LAUNCHER -p $Package 2>&1 | Out-Null
    } catch { }
    try {
        & $script:Adb -s $Serial shell am start -n "$Package/.MainActivity" 2>&1 | Out-Null
    } catch { }
    Write-Ok "Launch requested — complete Sync on the device UI"
}

# --- 6) enable immersion-tracker Hoshi poller (Drive by default) ---
if ($EnableTracker) {
    Write-Step "Enable hoshi block in config/settings.yaml (source=$Source)"
    $cfgPath = Join-Path $Root "config\settings.yaml"
    if (-not (Test-Path $cfgPath)) {
        Copy-Item (Join-Path $Root "config\settings.example.yaml") $cfgPath
    }
    $text = Get-Content $cfgPath -Raw -Encoding UTF8
    if ($text -notmatch "(?m)^hoshi:\s*$") {
        throw "No hoshi: section in settings.yaml — add from settings.example.yaml"
    }
    # enabled: true
    $text = [regex]::Replace($text, "(?m)^(\s*)enabled:\s*(true|false)\s*$", {
        param($m)
        # only first enabled under hoshi — fragile; do line-based edit instead
        $m.Value
    }, 1)

    $lines = Get-Content $cfgPath -Encoding UTF8
    $inHoshi = $false
    $hoshiIndent = 0
    $out = New-Object System.Collections.Generic.List[string]
    foreach ($line in $lines) {
        if ($line -match "^(hoshi:)\s*$") {
            $inHoshi = $true
            $out.Add($line)
            continue
        }
        if ($inHoshi -and $line -match "^[a-zA-Z]") {
            $inHoshi = $false
        }
        if ($inHoshi) {
            if ($line -match "^(\s+)enabled:\s*") {
                $out.Add("$($Matches[1])enabled: true")
                continue
            }
            if ($line -match "^(\s+)source:\s*") {
                $out.Add("$($Matches[1])source: $Source")
                continue
            }
        }
        $out.Add($line)
    }
    $out | Set-Content -Path $cfgPath -Encoding UTF8
    Write-Ok "hoshi.enabled=true source=$Source"
    Write-Info "Restart Docker so the scheduler picks it up:"
    Write-Info "  .\scripts\docker\rebuild.ps1"
    Write-Info "Or: docker compose restart immersion-tracker"
}

# --- 7) manual checklist (cannot do via ADB) ---
Write-Step "Manual steps on the Boox (ADB cannot do these)"
Write-Host @"
  1. In Hoshi: Settings → Sync (or Google Drive)
       - Connect the same Google account you use on the PC for Sheets (or a SA-shared folder account)
       - Enable sync / autosync for books + statistics
  2. Open a book, read a page, wait for sync (Wi‑Fi on)
  3. On PC: Drive should show folder  ttu-reader-data  with book subfolders
  4. If immersion-tracker uses a service account for Sheets, share  ttu-reader-data
     with that SA email as Viewer/Editor
  5. Enable tracker if you have not:  .\scripts\boox-hoshi-setup.ps1 -EnableTracker -Source drive
  6. Rebuild/restart Docker, then:
       Invoke-RestMethod -Method POST http://127.0.0.1:8000/api/hoshi/sync
"@

Write-Step "Done"
Write-Ok "Device ready for Hoshi. Progress logging = Drive poll (source=$Source), not ADB file reads."
Write-Info "Full guide: docs\HOSHI.md"
