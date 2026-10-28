const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const root = path.join(__dirname, '..');

test('Firefox release has the stable update feed and excludes local overrides', () => {
  execFileSync('pwsh', ['-NoProfile', '-File', 'scripts/pack-extension.ps1', '-FirefoxRelease'], { cwd: root });
  const result = execFileSync('pwsh', ['-NoProfile', '-Command', `
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead((Join-Path (Get-Location) 'dist/immersion-tracker-youtube-firefox-unsigned.zip'))
    try {
      $reader = [IO.StreamReader]::new($zip.GetEntry('manifest.json').Open())
      try { $manifest = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
      @{ manifest = $manifest; files = @($zip.Entries.FullName) } | ConvertTo-Json -Depth 30 -Compress
    } finally { $zip.Dispose() }
  `], { cwd: root, encoding: 'utf8' });
  const { manifest, files } = JSON.parse(result.trim());
  const source = JSON.parse(fs.readFileSync(path.join(root, 'extension/manifest.json'), 'utf8'));
  assert.equal(manifest.version, source.version);
  assert.equal(manifest.browser_specific_settings.gecko.id, 'immersion-tracker-youtube@local.dev');
  assert.equal(manifest.browser_specific_settings.gecko.update_url,
    'https://github.com/LucidPublicGit/immersion-tracker/releases/download/lit-firefox-updates/updates.json');
  assert.equal(manifest.background.service_worker, undefined);
  assert.deepEqual(manifest.optional_host_permissions, ['https://*/*']);
  assert.ok(files.includes('account-select.js'));
  assert.ok(files.includes('icons/icon-128.png'));
  assert.ok(files.every(name => !/local\.json|\.env|credentials|settings\.yaml/i.test(name)));
  assert.equal(source.browser_specific_settings.gecko.update_url, undefined);
});
