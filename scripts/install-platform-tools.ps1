# Download Google Android platform-tools (adb) into tools/platform-tools
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install-platform-tools.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Tools = Join-Path $Root "tools"
$Dest = Join-Path $Tools "platform-tools"
$Zip = Join-Path $Tools "platform-tools-windows.zip"
$Url = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"

New-Item -ItemType Directory -Force -Path $Tools | Out-Null

if (Test-Path (Join-Path $Dest "adb.exe")) {
    Write-Host "Already installed: $Dest\adb.exe"
    & (Join-Path $Dest "adb.exe") version
    exit 0
}

Write-Host "Downloading platform-tools..."
Invoke-WebRequest -Uri $Url -OutFile $Zip
Write-Host "Extracting to $Tools ..."
Expand-Archive -Path $Zip -DestinationPath $Tools -Force
Remove-Item $Zip -Force -ErrorAction SilentlyContinue

$Adb = Join-Path $Dest "adb.exe"
if (-not (Test-Path $Adb)) {
    throw "adb.exe missing after extract"
}
Write-Host "Installed: $Adb"
& $Adb version
Write-Host ""
Write-Host "Tip: add to PATH for this session:"
Write-Host "  `$env:Path = `"$Dest;`$env:Path`""
