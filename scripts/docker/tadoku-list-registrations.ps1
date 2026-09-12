# List Tadoku contest registrations (registration_id UUIDs).
# Prefers Queue UI session cookie; falls back to TADOKU_COOKIE.
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

function Invoke-List {
    param([string]$Python, [string[]]$Args)
    & $Python @Args
    return $LASTEXITCODE
}

$script = "/app/scripts/tadoku_list_registrations.py"
$hostScript = Join-Path $Root "scripts\tadoku_list_registrations.py"

# 1) Inside running container (has httpx + mounted data/)
$running = $false
try {
    $running = (docker inspect -f "{{.State.Running}}" immersion-tracker 2>$null) -eq "true"
} catch { }

if ($running) {
    Write-Host "Using container python..." -ForegroundColor DarkGray
    docker compose exec -T immersion-tracker python $script
    if ($LASTEXITCODE -eq 0) { exit 0 }
    Write-Host "Container run failed (exit $LASTEXITCODE); trying host python..." -ForegroundColor Yellow
}

# 2) Host venv / py
if (Test-Path .env) {
    Get-Content .env | ForEach-Object {
        if ($_ -match '^\s*TADOKU_COOKIE=(.*)$') {
            $env:TADOKU_COOKIE = $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
}

$pyCandidates = @(
    (Join-Path $Root ".venv\Scripts\python.exe"),
    "py",
    "python",
    "python3"
)
foreach ($py in $pyCandidates) {
    if ($py -match '[\\/]' -and -not (Test-Path $py)) { continue }
    try {
        & $py $hostScript
        if ($LASTEXITCODE -eq 0) { exit 0 }
        if ($LASTEXITCODE -eq 1) { exit 1 }
    } catch {
        continue
    }
}

Write-Host "Could not run tadoku_list_registrations.py. Is the tracker container up?" -ForegroundColor Red
exit 1
