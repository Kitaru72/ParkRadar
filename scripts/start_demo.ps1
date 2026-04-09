$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$existing = Get-Content -LiteralPath ".server.pid" -ErrorAction SilentlyContinue
if ($existing) {
  Write-Host "Server may already be running with PID $existing"
}

$process = Start-Process python -ArgumentList "-m", "app.main" -WorkingDirectory $projectRoot -PassThru
$process.Id | Set-Content -LiteralPath ".server.pid"

Write-Host "ParkRadar started"
Write-Host "User UI:  http://127.0.0.1:8000/"
Write-Host "Admin UI: http://127.0.0.1:8000/admin"
Write-Host "PID: $($process.Id)"
