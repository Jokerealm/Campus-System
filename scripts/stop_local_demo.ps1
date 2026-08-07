param(
  [int[]]$Ports = @(8000, 8001, 8002, 8103, 5176),
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Get-ProcessCommandLine {
  param([int]$ProcessId)
  $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
  if ($process) {
    return $process.CommandLine
  }
  return ""
}

function Test-IsRepoDemoProcess {
  param(
    [string]$CommandLine,
    [int]$Port
  )
  if (!$CommandLine -or $CommandLine -notlike "*$Root*") {
    return $false
  }
  if ($CommandLine -like "*uvicorn app.main:app*" -and $CommandLine -like "*--port $Port*") {
    return $true
  }
  if ($CommandLine -like "*manage.py runserver 127.0.0.1:$Port*") {
    return $true
  }
  if ($CommandLine -like "*vite*" -and $CommandLine -like "*$Port*") {
    return $true
  }
  return $false
}

$targetPids = New-Object System.Collections.Generic.HashSet[int]

foreach ($port in $Ports) {
  $listeners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
  foreach ($listener in $listeners) {
    $commandLine = Get-ProcessCommandLine $listener.OwningProcess
    if (Test-IsRepoDemoProcess $commandLine $port) {
      [void]$targetPids.Add([int]$listener.OwningProcess)
    }
  }

  $matchingProcesses = Get-CimInstance Win32_Process | Where-Object {
    Test-IsRepoDemoProcess $_.CommandLine $port
  }
  foreach ($process in $matchingProcesses) {
    [void]$targetPids.Add([int]$process.ProcessId)
  }
}

if ($targetPids.Count -eq 0) {
  Write-Host "No Campus-System local demo processes found."
  exit 0
}

foreach ($processId in ($targetPids | Sort-Object)) {
  $commandLine = Get-ProcessCommandLine $processId
  if ($DryRun) {
    Write-Host "Would stop PID ${processId}: $commandLine"
    continue
  }
  Write-Host "Stopping PID $processId"
  Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
}

if ($DryRun) {
  Write-Host "Dry run complete. No processes were stopped."
} else {
  Write-Host "Campus-System local demo processes stopped."
}
