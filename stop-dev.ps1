$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $root "runtime\preview.pid"

if (-not (Test-Path $pidFile)) {
  Write-Output "No preview process recorded."
  exit 0
}

$pidText = (Get-Content -Path $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
Remove-Item -Path $pidFile -Force -ErrorAction SilentlyContinue

if ($pidText -notmatch "^\d+$") {
  Write-Output "Preview pid file was invalid and has been cleared."
  exit 0
}

try {
  Stop-Process -Id ([int]$pidText) -Force -ErrorAction Stop
  Write-Output "Stopped preview process $pidText."
} catch {
  Write-Output "Preview process $pidText was not running."
}
