# Export current logs from the API to a local CSV folder (no Google required)
$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Base = if ($env:IMMERSION_URL) { $env:IMMERSION_URL.TrimEnd("/") } else { "http://127.0.0.1:8000" }
$OutDir = Join-Path $Root "data\local-exports"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logs = Invoke-RestMethod "$Base/api/logs?limit=500"
$metrics = Invoke-RestMethod "$Base/api/metrics"
$queue = Invoke-RestMethod "$Base/api/queue"

function Write-Csv($path, $rows) {
    if (-not $rows -or $rows.Count -eq 0) {
        Set-Content -Path $path -Value "(empty)" -Encoding utf8
        return
    }
    $rows | Export-Csv -Path $path -NoTypeInformation -Encoding utf8
}

Write-Csv (Join-Path $OutDir "logs-$stamp.csv") $logs
Write-Csv (Join-Path $OutDir "queue-$stamp.csv") $queue
$metrics | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $OutDir "metrics-$stamp.json") -Encoding utf8

Write-Host "Wrote exports under data\local-exports\" -ForegroundColor Green
Get-ChildItem $OutDir | Sort-Object LastWriteTime -Descending | Select-Object -First 6 | Format-Table Name, Length, LastWriteTime
