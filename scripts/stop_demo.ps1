$projectRoot = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $projectRoot ".server.pid"

if (-not (Test-Path $pidFile)) {
  Write-Host "No PID file found."
  exit 0
}

$serverPid = Get-Content -LiteralPath $pidFile
if ($serverPid) {
  Stop-Process -Id $serverPid -Force -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
  Write-Host "ParkRadar stopped"
}
