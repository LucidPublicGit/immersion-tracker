# OAuth path when service account KEYS are blocked by org policy
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

Write-Host @"

== Why you're here ==
Your org enforces: iam.disableServiceAccountKeyCreation
That blocks downloading service account JSON keys.

Workaround: sign in with YOUR Google user via OAuth (Desktop client).
That policy does NOT block OAuth client IDs.

"@ -ForegroundColor Yellow

$client = Join-Path $Root "data\google-oauth-client.json"
if (-not (Test-Path $client)) {
    Write-Host "Missing: data\google-oauth-client.json" -ForegroundColor Red
    Write-Host ""
    Write-Host "Do this in Google Cloud Console:"
    Write-Host "  1. APIs & Services → enable Sheets API + Drive API"
    Write-Host "  2. OAuth consent screen → configure (add yourself as test user if Testing)"
    Write-Host "  3. Credentials → Create credentials → OAuth client ID"
    Write-Host "       Application type: Desktop app"
    Write-Host "  4. Download JSON → save as:"
    Write-Host "       $client"
    Write-Host ""
    Write-Host "OR create a free personal GCP project (gmail.com) outside the org,"
    Write-Host "where SA keys are allowed — see docs\GOOGLE_SHEETS.md"
    exit 1
}

$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Creating venv + installing deps..." -ForegroundColor Cyan
    py -3.13 -m venv .venv
    $py = Join-Path $Root ".venv\Scripts\python.exe"
    & $py -m pip install -U pip -q
    & $py -m pip install -q -r requirements.txt
} else {
    & $py -m pip install -q google-auth-oauthlib gspread google-auth
}

Write-Host "Launching browser login..." -ForegroundColor Cyan
& $py (Join-Path $Root "scripts\google_oauth_login.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# Ensure settings paths
$settings = Join-Path $Root "config\settings.yaml"
if (Test-Path $settings) {
    $text = Get-Content $settings -Raw
    $text = $text -replace '(?m)^  enabled:\s*.*$', '  enabled: true'
    if ($text -notmatch 'oauth_token_file:') {
        $text = $text -replace '(?m)^  service_account_file:.*$',
            "  service_account_file: `"`"`n  oauth_client_secrets_file: `"/app/data/google-oauth-client.json`"`n  oauth_token_file: `"/app/data/google-oauth-token.json`""
    }
    Set-Content -Path $settings -Value $text -Encoding utf8
    Write-Host "Set sheets.enabled: true in config\settings.yaml (review file if needed)" -ForegroundColor Green
}

Write-Host "Restart Docker + sync..." -ForegroundColor Cyan
docker compose up -d --force-recreate
Start-Sleep -Seconds 4
& (Join-Path $PSScriptRoot "sheets-sync.ps1")
