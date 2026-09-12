# Pack the YouTube extension for install on this PC or copy to other machines.
# Output: dist/immersion-tracker-youtube.zip  (Chrome/Edge/Brave "Load unpacked" after extract,
#          or rename to .xpi and Load Temporary Add-on in Firefox)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Ext = Join-Path $Root "extension"
$Dist = Join-Path $Root "dist"
$Zip = Join-Path $Dist "immersion-tracker-youtube.zip"
$Xpi = Join-Path $Dist "immersion-tracker-youtube.xpi"

if (-not (Test-Path (Join-Path $Ext "manifest.json"))) {
    Write-Error "extension/manifest.json not found at $Ext"
}

New-Item -ItemType Directory -Force -Path $Dist | Out-Null
Remove-Item $Zip, $Xpi -ErrorAction SilentlyContinue

$files = @(
    "manifest.json",
    "background.js",
    "browser-api.js",
    "page-bridge.js",
    "content.js",
    "styles.css",
    "shared.js",
    "popup.html",
    "popup.js",
    "settings.html",
    "settings.js",
    "history.html",
    "history.js",
    "import.html",
    "import.js",
    "icons\icon-16.png",
    "icons\icon-32.png",
    "icons\icon-48.png",
    "icons\icon-64.png",
    "icons\icon-96.png",
    "icons\icon-128.png",
    "icons\icon-256.png"
)

Push-Location $Ext
try {
    Compress-Archive -Path $files -DestinationPath $Zip -Force
} finally {
    Pop-Location
}

Copy-Item $Zip $Xpi -Force

Write-Host ""
Write-Host "Packed:"
Write-Host "  $Zip"
Write-Host "  $Xpi"
Write-Host ""
Write-Host "Chrome / Edge / Brave:"
Write-Host "  1. Extract the zip to a folder (or use extension\ directly)"
Write-Host "  2. chrome://extensions → Developer mode → Load unpacked"
Write-Host ""
Write-Host "Firefox (temporary, survives until full restart):"
Write-Host "  about:debugging#/runtime/this-firefox → Load Temporary Add-on → pick the .xpi"
Write-Host "  (or select extension\manifest.json)"
Write-Host ""
Write-Host "Multi-PC: copy dist\ (or extension\) + set Server URL to this host"
Write-Host "  e.g. http://192.168.1.10:8000  and the same WEBHOOK_SECRET from .env"
Write-Host ""
