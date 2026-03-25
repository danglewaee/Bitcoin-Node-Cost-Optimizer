$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv311\Scripts\python.exe"
$previewScript = Join-Path $root "runtime\preview_stack.py"
$runtimeDir = Join-Path $root "runtime"
$logsDir = Join-Path $runtimeDir "logs"
$pidFile = Join-Path $runtimeDir "preview.pid"
$stdoutLog = Join-Path $logsDir "preview.out.log"
$stderrLog = Join-Path $logsDir "preview.err.log"
$previewUrl = "http://127.0.0.1:8899/?read_api_key=dev-read-key"

function Test-PreviewHealthy {
  try {
    $dashboard = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8899/" -TimeoutSec 2
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8765/health" -TimeoutSec 2
    return $dashboard.StatusCode -eq 200 -and $health.status -eq "ok"
  } catch {
    return $false
  }
}

function Stop-PreviewByPidFile {
  if (-not (Test-Path $pidFile)) {
    return
  }

  $pidText = (Get-Content -Path $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
  Remove-Item -Path $pidFile -Force -ErrorAction SilentlyContinue

  if ($pidText -notmatch "^\d+$") {
    return
  }

  try {
    Stop-Process -Id ([int]$pidText) -Force -ErrorAction Stop
    Start-Sleep -Milliseconds 600
  } catch {
  }
}

if (-not (Test-Path $python)) {
  throw "Python env not found at $python"
}

if (-not (Test-Path $previewScript)) {
  throw "Preview script not found at $previewScript"
}

if (Test-PreviewHealthy) {
  Write-Output $previewUrl
  exit 0
}

Stop-PreviewByPidFile

New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
Remove-Item -Path $stdoutLog, $stderrLog -Force -ErrorAction SilentlyContinue

$process = Start-Process `
  -FilePath $python `
  -ArgumentList $previewScript `
  -WorkingDirectory $root `
  -RedirectStandardOutput $stdoutLog `
  -RedirectStandardError $stderrLog `
  -PassThru

Set-Content -Path $pidFile -Value $process.Id

$deadline = (Get-Date).AddSeconds(25)
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Milliseconds 500

  if ($process.HasExited) {
    $stdout = if (Test-Path $stdoutLog) { Get-Content -Path $stdoutLog -Tail 40 | Out-String } else { "" }
    $stderr = if (Test-Path $stderrLog) { Get-Content -Path $stderrLog -Tail 40 | Out-String } else { "" }
    throw "Preview process exited early.`nSTDOUT:`n$stdout`nSTDERR:`n$stderr"
  }

  if (Test-PreviewHealthy) {
    Write-Output $previewUrl
    exit 0
  }
}

$stdout = if (Test-Path $stdoutLog) { Get-Content -Path $stdoutLog -Tail 40 | Out-String } else { "" }
$stderr = if (Test-Path $stderrLog) { Get-Content -Path $stderrLog -Tail 40 | Out-String } else { "" }
throw "Preview did not become healthy in time.`nSTDOUT:`n$stdout`nSTDERR:`n$stderr"
