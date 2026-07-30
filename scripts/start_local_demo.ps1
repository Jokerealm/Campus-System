param(
  [int]$P2Port = 8000,
  [int]$P3Port = 8103,
  [int]$FrontendPort = 5176
)

$ErrorActionPreference = "Stop"
try {
  [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
  $OutputEncoding = [Console]::OutputEncoding
} catch {
}

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$RunDir = Join-Path $Root "data\run"
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null

function Resolve-NodeBin {
  $bundledNodeBin = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin"
  if (Test-Path $bundledNodeBin) {
    return $bundledNodeBin
  }

  $nodeCommand = Get-Command node -ErrorAction SilentlyContinue
  if ($nodeCommand) {
    return (Split-Path $nodeCommand.Source -Parent)
  }

  return ""
}

function Resolve-Pnpm {
  $bundledPnpm = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback\pnpm.cmd"
  if (Test-Path $bundledPnpm) {
    return $bundledPnpm
  }

  $pnpmCommand = Get-Command pnpm -ErrorAction SilentlyContinue
  if ($pnpmCommand) {
    return $pnpmCommand.Source
  }

  throw "pnpm is not available. Install Node.js 22+ and pnpm, or run 'corepack enable' before starting the demo."
}

function Import-LocalEnv {
  param([string]$Path)

  if (!(Test-Path $Path)) {
    return
  }

  foreach ($rawLine in Get-Content $Path) {
    $line = $rawLine.Trim()
    if (!$line -or $line.StartsWith("#") -or !$line.Contains("=")) {
      continue
    }
    $key, $value = $line.Split("=", 2)
    $key = $key.Trim().TrimStart([char]0xFEFF)
    $value = $value.Trim().Trim('"').Trim("'")
    if ($key -match "^[A-Za-z_][A-Za-z0-9_]*$" -and ![Environment]::GetEnvironmentVariable($key, "Process")) {
      Set-Item -Path "Env:$key" -Value $value
    }
  }
}

function Test-HttpOk {
  param([string]$Url)

  try {
    $null = Invoke-RestMethod -Uri $Url -TimeoutSec 3
    return $true
  } catch {
    return $false
  }
}

function Wait-HttpOk {
  param(
    [string]$Url,
    [string]$Name,
    [int]$Retries = 40,
    [int]$DelayMs = 750
  )

  for ($i = 1; $i -le $Retries; $i += 1) {
    try {
      $response = Invoke-RestMethod -Uri $Url -TimeoutSec 3
      return $response
    } catch {
      Start-Sleep -Milliseconds $DelayMs
    }
  }
  throw "$Name did not become ready at $Url"
}

function Get-PortOwnerSummary {
  param([int]$Port)

  $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  $summaries = @()
  foreach ($listener in $listeners) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)" -ErrorAction SilentlyContinue
    if ($process) {
      $summaries += "PID $($process.ProcessId): $($process.CommandLine)"
    } else {
      $summaries += "PID $($listener.OwningProcess)"
    }
  }
  return ($summaries -join "`n")
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

function Stop-StaleRepoDemoPort {
  param(
    [int]$Port,
    [string]$Name
  )

  $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  $stopped = $false
  $unknownOwners = @()
  foreach ($listener in $listeners) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)" -ErrorAction SilentlyContinue
    $commandLine = if ($process) { $process.CommandLine } else { "" }
    if (Test-IsRepoDemoProcess $commandLine $Port) {
      Write-Host "$Name on port $Port failed readiness; stopping stale Campus-System demo PID $($listener.OwningProcess)."
      Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
      $stopped = $true
    } else {
      $unknownOwners += "PID $($listener.OwningProcess): $commandLine"
    }
  }

  if ($unknownOwners.Count -gt 0) {
    throw @"
$Name port $Port is already occupied by a process that does not look like this repository's demo service.

$($unknownOwners -join "`n")

Choose another port or stop that process manually.
"@
  }

  if ($stopped) {
    for ($i = 1; $i -le 20; $i += 1) {
      $remaining = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
      if (!$remaining) {
        return $true
      }
      Start-Sleep -Milliseconds 250
    }
    throw "$Name port $Port is still occupied after stopping stale repository demo processes."
  }

  return $false
}

function Test-ServiceSlot {
  param(
    [int]$Port,
    [string]$Name,
    [string]$ReadyUrl
  )

  $listeners = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  if (!$listeners) {
    return $true
  }
  if (Test-HttpOk $ReadyUrl) {
    Write-Host "$Name already running on port $Port; reusing it."
    return $false
  }

  if (Stop-StaleRepoDemoPort $Port $Name) {
    return $true
  }

  $ownerSummary = Get-PortOwnerSummary $Port
  throw @"
$Name port $Port is already occupied, but its readiness check failed: $ReadyUrl

$ownerSummary

Run .\scripts\stop_local_demo.ps1 -Ports $Port, or choose another port.
"@
}

Import-LocalEnv (Join-Path $Root ".env")

if (!$env:CAMPUS_LLM_BASE_URL) {
  $env:CAMPUS_LLM_BASE_URL = "https://token.zy-cjk.cn/v1"
}

$NodeBin = Resolve-NodeBin
$Pnpm = Resolve-Pnpm
if ($NodeBin) {
  $env:Path = "$NodeBin;$env:Path"
}
Write-Host "Using pnpm: $Pnpm"

$startP3 = Test-ServiceSlot $P3Port "P3 API" "http://127.0.0.1:$P3Port/api/health/"
$startP2 = Test-ServiceSlot $P2Port "P2 API" "http://127.0.0.1:$P2Port/api/demo/readiness"
$startFrontend = Test-ServiceSlot $FrontendPort "Frontend" "http://127.0.0.1:$FrontendPort"

if (!(Test-Path $VenvPython)) {
  python -m venv (Join-Path $Root ".venv")
}

Write-Host "Installing Python dependencies..."
& $VenvPython -m pip install --disable-pip-version-check --quiet -r (Join-Path $Root "backend\requirements.txt") -r (Join-Path $Root "campus_p3\requirements.txt")

$env:P3_DATABASE_ENGINE = "sqlite"
$env:P3_SQLITE_PATH = Join-Path $Root "data\p3_demo.sqlite3"
if ($startP3) {
  & $VenvPython (Join-Path $Root "campus_p3\backend\manage.py") migrate --noinput
  & $VenvPython (Join-Path $Root "campus_p3\backend\manage.py") load_knowledge_points
  & $VenvPython (Join-Path $Root "campus_p3\backend\manage.py") load_question_bank
  & $VenvPython (Join-Path $Root "campus_p3\backend\manage.py") import_p1_papers_to_bank
} else {
  Write-Host "Skipping P3 migration/import because an existing P3 service is being reused."
}

Write-Host "Installing frontend dependencies..."
& $Pnpm --dir (Join-Path $Root "frontend") install --silent

$p3Log = Join-Path $RunDir "p3-$P3Port.log"
$p3Err = Join-Path $RunDir "p3-$P3Port.err.log"
$p2Log = Join-Path $RunDir "p2-$P2Port.log"
$p2Err = Join-Path $RunDir "p2-$P2Port.err.log"
$frontendLog = Join-Path $RunDir "frontend-$FrontendPort.log"
$frontendErr = Join-Path $RunDir "frontend-$FrontendPort.err.log"

if ($startP3) {
  Start-Process -WindowStyle Hidden -WorkingDirectory (Join-Path $Root "campus_p3\backend") -FilePath $VenvPython -ArgumentList "manage.py runserver 127.0.0.1:$P3Port" -RedirectStandardOutput $p3Log -RedirectStandardError $p3Err
}

$p2DbPath = Join-Path $Root "data\p2_demo.sqlite3"
$p2Command = "`$env:CAMPUS_P3_BASE_URL='http://127.0.0.1:$P3Port'; `$env:CAMPUS_P2_SQLITE_PATH='$p2DbPath'; & '$VenvPython' -m uvicorn app.main:app --host 127.0.0.1 --port $P2Port"
if ($startP2) {
  Start-Process -WindowStyle Hidden -WorkingDirectory (Join-Path $Root "backend") -FilePath "powershell.exe" -ArgumentList "-NoProfile", "-Command", $p2Command -RedirectStandardOutput $p2Log -RedirectStandardError $p2Err
}

$frontendPathPrefix = if ($NodeBin) { "`$env:Path='$NodeBin;' + `$env:Path; " } else { "" }
$frontendCommand = "$frontendPathPrefix`$env:VITE_API_BASE_URL='http://127.0.0.1:$P2Port'; & '$Pnpm' dev --host 127.0.0.1 --port $FrontendPort"
if ($startFrontend) {
  Start-Process -WindowStyle Hidden -WorkingDirectory (Join-Path $Root "frontend") -FilePath "powershell.exe" -ArgumentList "-NoProfile", "-Command", $frontendCommand -RedirectStandardOutput $frontendLog -RedirectStandardError $frontendErr
}

Write-Host "Waiting for local services..."
$null = Wait-HttpOk "http://127.0.0.1:$P3Port/api/health/" "P3 API"
$null = Wait-HttpOk "http://127.0.0.1:$P2Port/api/health" "P2 API"
$readiness = Wait-HttpOk "http://127.0.0.1:$P2Port/api/demo/readiness" "P2 readiness"
$null = Wait-HttpOk "http://127.0.0.1:$FrontendPort" "Frontend"

Write-Host "P2 API: http://127.0.0.1:$P2Port"
Write-Host "P3 API: http://127.0.0.1:$P3Port/api/docs/"
$frontendDemoUrl = "http://127.0.0.1:$FrontendPort/?apiBase=$([System.Uri]::EscapeDataString("http://127.0.0.1:$P2Port"))"
Write-Host "Frontend: $frontendDemoUrl"

if ($readiness.data) {
  $facts = $readiness.data.facts
  $components = ($readiness.data.components | ForEach-Object { "$($_.key)=$($_.status)" }) -join "; "
  Write-Host "Readiness: $($readiness.data.overall_status)"
  Write-Host "Catalog: papers=$($facts.paper_count), questions=$($facts.question_count), knowledge_points=$($facts.knowledge_point_count)"
  Write-Host "Components: $components"
}

Write-Host "Logs: $RunDir"
