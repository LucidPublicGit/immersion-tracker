# Initialize Google Sheets integration:
#  - checks for service account JSON
#  - creates a spreadsheet (tabs + headers) if needed
#  - patches config/settings.yaml
#  - restarts container and runs a sync
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

Write-Host "== Google Sheets init ==" -ForegroundColor Cyan
Write-Host ""
Write-Host "How this works:" -ForegroundColor Yellow
Write-Host "  Google Sheets is NOT a file on your PC that Docker mounts."
Write-Host "  It lives in Google Drive (cloud). Docker calls Google APIs with a"
Write-Host "  service-account key file that YOU place in data\ on the host."
Write-Host "  That folder is mounted:  ./data  ->  /app/data  inside the container."
Write-Host ""

$sa = Join-Path $Root "data\google-service-account.json"
if (-not (Test-Path $sa)) {
    Write-Host "Missing: data\google-service-account.json" -ForegroundColor Red
    Write-Host ""
    Write-Host "Steps:"
    Write-Host "  1. https://console.cloud.google.com/ → create/select a project"
    Write-Host "  2. Enable APIs: Google Sheets API + Google Drive API"
    Write-Host "  3. IAM → Service Accounts → Create → Keys → JSON"
    Write-Host "  4. Save the file as:"
    Write-Host "       $sa"
    Write-Host "  5. Re-run this script"
    Write-Host ""
    Write-Host "Optional: create the sheet yourself in the browser, share it with the"
    Write-Host "service account email (Editor), put spreadsheet_id in config\settings.yaml"
    exit 1
}

# Prefer local venv python if present
$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    $py = "py"
    $pyArgs = @("-3.13")
} else {
    $pyArgs = @()
}

$share = Read-Host "Your Gmail to share the sheet with (Editor) — leave blank to skip"
$createArgs = @(
    "scripts\create_google_sheet.py",
    "--credentials", "data\google-service-account.json"
)
if ($share) {
    $createArgs += @("--share-with", $share)
}

Write-Host "Creating spreadsheet..." -ForegroundColor Cyan
if ($pyArgs.Count -gt 0) {
    & $py @pyArgs -m pip install -q gspread google-auth 2>$null
    & $py @pyArgs @createArgs
} else {
    & $py -m pip install -q gspread google-auth 2>$null
    & $py @createArgs
}
if ($LASTEXITCODE -ne 0) {
    Write-Host "Local create failed; trying inside Docker image..." -ForegroundColor Yellow
    $dockerArgs = @(
        "compose", "run", "--rm", "--no-deps",
        "immersion-tracker",
        "python", "/app/scripts/create_google_sheet.py",
        "--credentials", "/app/data/google-service-account.json"
    )
    if ($share) {
        $dockerArgs += @("--share-with", $share)
    }
    docker @dockerArgs
}

$info = Join-Path $Root "data\google-sheet-info.txt"
if (-not (Test-Path $info)) {
    Write-Host "Sheet info file not found — create may have failed." -ForegroundColor Red
    exit 1
}

$idLine = Get-Content $info | Where-Object { $_ -like "spreadsheet_id=*" } | Select-Object -First 1
$spreadsheetId = $idLine -replace "^spreadsheet_id=", ""
$urlLine = Get-Content $info | Where-Object { $_ -like "url=*" } | Select-Object -First 1
$url = $urlLine -replace "^url=", ""

Write-Host "Spreadsheet ID: $spreadsheetId" -ForegroundColor Green
Write-Host "Open: $url" -ForegroundColor Green

# Patch settings.yaml sheets section simply by rewriting known keys via Python if available
$settings = Join-Path $Root "config\settings.yaml"
$patchPy = @"
from pathlib import Path
import re
p = Path(r'$($settings -replace '\\','/')')
text = p.read_text(encoding='utf-8')
# enable sheets + set id + service account path
def set_key(text, key, value, indent='  '):
    pat = rf'(?m)^{indent}{key}:\s*.*$'
    repl = f'{indent}{key}: {value}'
    if re.search(pat, text):
        return re.sub(pat, repl, text, count=1)
    return text
text = set_key(text, 'enabled', 'true')
# only within sheets block is hard; do global-ish safe replaces for known structure
text = re.sub(r'(?m)^  enabled:\s*.*$', '  enabled: true', text, count=1)
text = re.sub(r'(?m)^  spreadsheet_id:\s*.*$', f'  spreadsheet_id: \"{spreadsheetId}\"', text, count=1)
text = re.sub(r'(?m)^  service_account_file:\s*.*$', '  service_account_file: \"/app/data/google-service-account.json\"', text, count=1)
p.write_text(text, encoding='utf-8')
print('Updated config/settings.yaml')
"@

if (Test-Path (Join-Path $Root ".venv\Scripts\python.exe")) {
    & (Join-Path $Root ".venv\Scripts\python.exe") -c $patchPy
} else {
    py -3.13 -c $patchPy
}

Write-Host "Restarting container to pick up config..." -ForegroundColor Cyan
docker compose up -d --force-recreate

Start-Sleep -Seconds 3
Write-Host "Syncing..." -ForegroundColor Cyan
& (Join-Path $PSScriptRoot "sheets-sync.ps1")

Write-Host ""
Write-Host "Done. Open the sheet in your browser:" -ForegroundColor Green
Write-Host "  $url"
Write-Host "Manual logs: use the 'Manual Entry' tab, leave 'imported' blank, then sheets-sync."
