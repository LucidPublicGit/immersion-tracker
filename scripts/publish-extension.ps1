# Called only after Mozilla signing succeeds. Never publishes unsigned artifacts.
param([string]$SignedDirectory = "$PSScriptRoot/../dist/signed")
$ErrorActionPreference = 'Stop'
$repo = 'LucidPublicGit/immersion-tracker'
$feedTag = 'lit-firefox-updates'
$root = Split-Path -Parent $PSScriptRoot
$manifest = Get-Content -LiteralPath "$root/extension/manifest.json" -Raw | ConvertFrom-Json
$version = $manifest.version
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw 'Expected a three-part release version' }
$files = @(Get-ChildItem -LiteralPath $SignedDirectory -Filter '*.xpi')
if ($files.Count -ne 1) { throw 'Expected exactly one signed XPI' }
$tag = "lit-firefox-v$version"
$name = "lit-firefox-$version.xpi"
$artifact = Join-Path "$root/dist" $name
Copy-Item -LiteralPath $files[0].FullName -Destination $artifact -Force
# Inspect signed identity and update URL before publishing.
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::OpenRead($artifact)
try {
    $reader = [IO.StreamReader]::new($zip.GetEntry('manifest.json').Open())
    try { $signedManifest = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
    if ($signedManifest.version -ne $version -or $signedManifest.browser_specific_settings.gecko.id -ne $manifest.browser_specific_settings.gecko.id) { throw 'Signed artifact identity mismatch' }
    $feedUrl = "https://github.com/$repo/releases/download/$feedTag/updates.json"
    if ($signedManifest.browser_specific_settings.gecko.update_url -ne $feedUrl) { throw 'Signed artifact has incorrect update URL' }
    if (!$zip.GetEntry('META-INF/mozilla.rsa')) { throw 'Mozilla signing metadata missing' }
} finally { $zip.Dispose() }

& gh release view $tag --repo $repo *> $null
if ($LASTEXITCODE -eq 0) { throw "Release $tag already exists; increment the extension version before publishing" }
& gh release create $tag $artifact --repo $repo --target $env:GITHUB_SHA --title "LiT Firefox $version" --notes 'Signed Firefox release. Existing installations with the LiT update feed update automatically.' --latest=false
if ($LASTEXITCODE -ne 0) { throw 'Versioned release failed; update feed unchanged' }
$url = "https://github.com/$repo/releases/download/$tag/$name"
$response = Invoke-WebRequest -Uri $url -Method Head
if ($response.StatusCode -ne 200) { throw 'Signed download unavailable; update feed unchanged' }
$hash = (Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash.ToLowerInvariant()
$feed = @{ addons = @{ $manifest.browser_specific_settings.gecko.id = @{ updates = @(@{ version = $version; update_link = $url; update_hash = "sha256:$hash" }) } } }
$feedPath = "$root/dist/updates.json"
[IO.File]::WriteAllText($feedPath, ($feed | ConvertTo-Json -Depth 10), [Text.UTF8Encoding]::new($false))
& gh release view $feedTag --repo $repo *> $null
if ($LASTEXITCODE -ne 0) {
    & gh release create $feedTag --repo $repo --target $env:GITHUB_SHA --title 'LiT Firefox automatic updates' --notes 'Stable Firefox update feed. Install a versioned signed XPI once to enable updates.' --latest=false
    if ($LASTEXITCODE -ne 0) { throw 'Could not create feed release' }
}
# Publish last: clients never see a feed advertising an unsigned or missing XPI.
& gh release upload $feedTag $feedPath --repo $repo --clobber
if ($LASTEXITCODE -ne 0) { throw 'Feed upload failed' }
Write-Host "Published LiT $version and updated $feedUrl"
