# Host-side Hoshi ADB poll → immersion-tracker API
# Docker on Windows cannot use USB ADB; run this on the host while Boox is plugged in.
#
#   .\scripts\hoshi_adb_poll.ps1
#   .\scripts\hoshi_adb_poll.ps1 -DryRun
#   .\scripts\hoshi_adb_poll.ps1 -Connect "192.168.1.50:5555"

param(
    [string]$Api = "http://127.0.0.1:8000",
    [switch]$DryRun,
    [string]$Connect = "",
    [string]$Serial = "",
    [string]$Binary = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$AdbCandidates = @(
    $Binary,
    (Join-Path $Root "tools\platform-tools\adb.exe"),
    "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
) | Where-Object { $_ -and $_.Trim() }

$Adb = $null
foreach ($c in $AdbCandidates) {
    if (Test-Path $c) { $Adb = (Resolve-Path $c).Path; break }
}
if (-not $Adb) {
    $cmd = Get-Command adb -ErrorAction SilentlyContinue
    if ($cmd) { $Adb = $cmd.Source }
}
if (-not $Adb) {
    Write-Host "adb not found. Installing platform-tools into tools\ ..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\install-platform-tools.ps1")
    $Adb = Join-Path $Root "tools\platform-tools\adb.exe"
}
if (-not (Test-Path $Adb)) {
    throw "adb still missing after install attempt"
}

Write-Host "Using adb: $Adb"
& $Adb devices -l

$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    $py = "python"
}

$args = @(
    (Join-Path $Root "scripts\hoshi_adb_poll.py"),
    "--api", $Api,
    "--binary", $Adb
)
if ($DryRun) { $args += "--dry-run" }
if ($Connect) { $args += @("--connect", $Connect) }
if ($Serial) { $args += @("--serial", $Serial) }

& $py @args
exit $LASTEXITCODE
