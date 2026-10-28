# Pack the YouTube extension for install on this PC or copy to other machines.
# Output: dist/immersion-tracker-youtube.zip  (Chrome/Edge/Brave "Load unpacked" after extract,
#          or rename to .xpi and Load Temporary Add-on in Firefox)

param([switch]$FirefoxRelease)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Ext = Join-Path $Root "extension"
$Dist = Join-Path $Root "dist"
$Zip = Join-Path $Dist "immersion-tracker-youtube.zip"
$Xpi = Join-Path $Dist "immersion-tracker-youtube.xpi"
if ($FirefoxRelease) {
    $Zip = Join-Path $Dist "immersion-tracker-youtube-firefox-unsigned.zip"
    $Xpi = Join-Path $Dist "immersion-tracker-youtube-firefox-unsigned.xpi"
}

if (-not (Test-Path (Join-Path $Ext "manifest.json"))) {
    Write-Error "extension/manifest.json not found at $Ext"
}

New-Item -ItemType Directory -Force -Path $Dist | Out-Null
Remove-Item $Zip, $Xpi -ErrorAction SilentlyContinue

$files = @(
    "manifest.json",
    "account-select.js",
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
    "privacy.html",
    "history.html",
    "history.js",
    "import.html",
    "import.js",
    "import-redirect.js",
    "icons\icon-16.png",
    "icons\icon-32.png",
    "icons\icon-48.png",
    "icons\icon-64.png",
    "icons\icon-96.png",
    "icons\icon-128.png",
    "icons\icon-256.png"
)

$Stage = Join-Path ([IO.Path]::GetTempPath()) ("immersion-extension-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $Stage | Out-Null
try {
    foreach ($file in $files) {
        $target = Join-Path $Stage $file
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
        Copy-Item -LiteralPath (Join-Path $Ext $file) -Destination $target
    }
    if ($FirefoxRelease) {
        $manifestPath = Join-Path $Stage "manifest.json"
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        # Use Firefox's built-in data consent; older Firefox needs a custom consent UI.
        $manifest.browser_specific_settings.gecko.strict_min_version = "140.0"
        $manifest.browser_specific_settings.gecko | Add-Member -NotePropertyName update_url -NotePropertyValue "https://github.com/LucidPublicGit/immersion-tracker/releases/download/lit-firefox-updates/updates.json" -Force
        $manifest.browser_specific_settings | Add-Member -NotePropertyName gecko_android -NotePropertyValue @{ strict_min_version = "142.0" } -Force
        $manifest.optional_host_permissions = @("https://*/*")
        $manifest | Add-Member -NotePropertyName incognito -NotePropertyValue "not_allowed" -Force
        $manifest.browser_specific_settings.gecko | Add-Member -NotePropertyName data_collection_permissions -NotePropertyValue @{
            required = @("browsingActivity", "websiteActivity", "websiteContent", "personallyIdentifyingInfo", "authenticationInfo")
        } -Force
        $manifest.background.PSObject.Properties.Remove("service_worker")
        $json = $manifest | ConvertTo-Json -Depth 30
        [IO.File]::WriteAllText($manifestPath, $json, (New-Object Text.UTF8Encoding $false))
    }
    # Zip entries must preserve icons/ paths on every PowerShell version.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [IO.Compression.ZipFile]::CreateFromDirectory($Stage, $Zip)
} finally {
    # Only remove the unique staging directory created above.
    if ((Split-Path -Parent ([IO.Path]::GetFullPath($Stage))) -eq ([IO.Path]::GetTempPath()).TrimEnd('\', '/')) {
        Remove-Item -LiteralPath $Stage -Recurse -Force
    }
}

Copy-Item $Zip $Xpi -Force

Write-Host ""
Write-Host "Packed:"
Write-Host "  $Zip"
Write-Host "  $Xpi"
Write-Host ""
if ($FirefoxRelease) {
    Write-Host "UNSIGNED submission candidate for Firefox 140+. Not permanently installable yet."
    Write-Host "Upload the zip at https://addons.mozilla.org/developers/addon/submit/distribution"
    Write-Host "Choose 'On your own', then download Mozilla's SIGNED XPI."
    Write-Host "Install that signed file through about:addons -> Install Add-on From File."
    Write-Host "See docs/YOUTUBE_EXTENSION_PUBLISHING.md for review concerns and update options."
    return
}
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
