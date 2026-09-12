#Requires -Version 5.1
<#
.SYNOPSIS
  Repair AnkiConnect for Anki 25.09.x (uv launcher / pythonw).

.DESCRIPTION
  Anki 25.09 does not show as process name "anki.exe" — it runs as pythonw
  via the launcher. AnkiConnect only starts AFTER a profile is fully open
  (deck browser visible).

  This script reinstalls a clean AnkiConnect package from AnkiWeb and applies
  compatibility patches:
    * version parser handles "25.09.4 (hash)" style strings
    * util.setting never raises (safe getConfig)
    * initLogging never blocks the HTTP server
    * meta.json max_point_version raised for 25.x
    * CORS list includes host.docker.internal for Docker

.USAGE
  1. Close Anki completely
  2. .\scripts\fix-ankiconnect.ps1
  3. When Anki opens, select your profile (User 1) until the DECK LIST is visible
  4. Script will probe http://127.0.0.1:8765
#>
[CmdletBinding()]
param([switch]$SkipDownload)

$ErrorActionPreference = "Stop"
$AddonId = "2055492159"
$AddonDir = Join-Path $env:APPDATA "Anki2\addons21\$AddonId"
$Tmp = Join-Path $env:TEMP "anki-connect-fix"
$AnkiExe = Join-Path $env:LOCALAPPDATA "Programs\Anki\anki.exe"
$Py = Join-Path $env:LOCALAPPDATA "AnkiProgramFiles\.venv\Scripts\python.exe"

Write-Host "==> Preparing clean AnkiConnect under $AddonDir"
New-Item -ItemType Directory -Force -Path $Tmp | Out-Null
if (-not $SkipDownload) {
    $zip = Join-Path $Tmp "addon.zip"
    Write-Host "    Downloading from AnkiWeb..."
    Invoke-WebRequest -Uri "https://ankiweb.net/shared/download/$AddonId`?v=2.1&p=250900" `
        -OutFile $zip -UseBasicParsing
    $extract = Join-Path $Tmp "extracted"
    if (Test-Path $extract) { Remove-Item $extract -Recurse -Force }
    Expand-Archive -Path $zip -DestinationPath $extract -Force
} else {
    $extract = Join-Path $Tmp "extracted"
    if (-not (Test-Path (Join-Path $extract "__init__.py"))) {
        throw "No cached package; run without -SkipDownload"
    }
}

New-Item -ItemType Directory -Force -Path $AddonDir | Out-Null
foreach ($f in @("__init__.py", "web.py", "edit.py", "util.py", "config.md")) {
    Copy-Item (Join-Path $extract $f) (Join-Path $AddonDir $f) -Force
}

if (-not (Test-Path $Py)) {
    Write-Host "Anki python not found at $Py — applying patches with system python" -ForegroundColor Yellow
    $Py = "python"
}

Write-Host "==> Applying Anki 25.09 compatibility patches"
& $Py -c @"
from pathlib import Path
import json
dest = Path(r'$AddonDir')

util_path = dest / 'util.py'
util = util_path.read_text(encoding='utf-8')
old = '''def setting(key):
    try:
        return aqt.mw.addonManager.getConfig(__name__).get(key, DEFAULT_CONFIG[key])
    except:
        raise Exception('setting {} not found'.format(key))
'''
new = '''def setting(key):
    \"\"\"Return config value; never raise (safe on Anki 25.09).\"\"\"
    try:
        mgr = getattr(getattr(aqt, 'mw', None), 'addonManager', None)
        if mgr is not None:
            mod = __name__.split('.')[0] if __name__ else __name__
            cfg = mgr.getConfig(mod) or mgr.getConfig(__name__) or {}
            if isinstance(cfg, dict) and key in cfg:
                return cfg[key]
    except Exception:
        pass
    if key in DEFAULT_CONFIG:
        return DEFAULT_CONFIG[key]
    return None
'''
if old not in util:
    raise SystemExit('util.setting block not found — AnkiConnect upstream may have changed')
util_path.write_text(util.replace(old, new), encoding='utf-8')

init_path = dest / '__init__.py'
init = init_path.read_text(encoding='utf-8')
old_ver = '''version_string = aqt.appVersion
for suffix in VERSION_SUFFIXES:
    version_string = version_string.replace(suffix, \".\")
anki_version = tuple(int(segment) for segment in version_string.split(\".\") if segment)
'''
new_ver = '''version_string = aqt.appVersion
version_string = str(version_string).split(\" \")[0].strip()
for suffix in VERSION_SUFFIXES:
    version_string = version_string.replace(suffix, \".\")
anki_version = tuple(int(segment) for segment in version_string.split(\".\") if segment.isdigit())
'''
if old_ver not in init:
    raise SystemExit('version parser block not found')
init = init.replace(old_ver, new_ver)

old_log = '''    def initLogging(self):
        logPath = util.setting('apiLogPath')
        if logPath is not None:
            self.log = open(logPath, 'w')
'''
new_log = '''    def initLogging(self):
        try:
            logPath = util.setting('apiLogPath')
            if logPath:
                self.log = open(logPath, 'w', encoding='utf-8')
        except Exception:
            self.log = None
'''
if old_log not in init:
    raise SystemExit('initLogging block not found')
init = init.replace(old_log, new_log)
init_path.write_text(init, encoding='utf-8')

(dest / 'meta.json').write_text(json.dumps({
    'name': 'AnkiConnect',
    'mod': 1762717231,
    'min_point_version': 45,
    'max_point_version': 251200,
    'branch_index': 0,
    'disabled': False,
    'conflicts': [],
    'update_enabled': True,
}, indent=2), encoding='utf-8')
(dest / 'config.json').write_text(json.dumps({
    'apiKey': None,
    'apiLogPath': None,
    'webBindAddress': '127.0.0.1',
    'webBindPort': 8765,
    'webCorsOriginList': [
        'http://localhost',
        'http://127.0.0.1',
        'http://host.docker.internal',
        '*',
    ],
    'ignoreOriginList': [],
}, indent=2), encoding='utf-8')
print('patches ok')
"@

Write-Host "==> Starting Anki"
if (Test-Path $AnkiExe) { Start-Process $AnkiExe } else { Write-Host "Start Anki manually" -ForegroundColor Yellow }

Write-Host @"

************************************************************************
  Open your Anki PROFILE now (e.g. User 1) until you see the DECK LIST.
  AnkiConnect does NOT start on the launcher / profile chooser screen.
************************************************************************
"@ -ForegroundColor Cyan

Write-Host "==> Probing http://127.0.0.1:8765 (up to ~2 min)..."
$ok = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep 2
    try {
        $r = Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:8765" `
            -ContentType "application/json" `
            -Body '{"action":"version","version":6}' -TimeoutSec 2
        Write-Host "SUCCESS: $($r | ConvertTo-Json -Compress)" -ForegroundColor Green
        $ok = $true
        break
    } catch {
        if ($i % 5 -eq 0) {
            Write-Host "  still waiting… open the deck browser if you have not yet ($i)"
        }
    }
}

if (-not $ok) {
    Write-Host @"

Still no listener on :8765.

In Anki (with deck browser open):
  Tools → Add-ons → confirm AnkiConnect is listed and enabled
  Tools → Add-ons → View Add-on Errors  (copy anything about 2055492159)

Then re-run:
  .\scripts\fix-ankiconnect.ps1
"@ -ForegroundColor Yellow
    exit 2
}

Write-Host @"

Host AnkiConnect is up. Check immersion-tracker:
  Invoke-RestMethod http://127.0.0.1:8000/api/anki/status
  Invoke-RestMethod -Method POST http://127.0.0.1:8000/api/anki/sync

Leave Anki open (profile loaded) while you study.
"@ -ForegroundColor Cyan
