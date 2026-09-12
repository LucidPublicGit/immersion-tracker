# List Tadoku contest registrations (shows registration_id UUIDs)
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

# Load TADOKU_COOKIE from .env into process env for the Python script
if (Test-Path .env) {
    Get-Content .env | ForEach-Object {
        if ($_ -match '^\s*TADOKU_COOKIE=(.*)$') {
            $env:TADOKU_COOKIE = $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
}

$py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "py" }

& $py (Join-Path $Root "scripts\tadoku_list_registrations.py")
