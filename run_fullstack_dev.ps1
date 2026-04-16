#!/usr/bin/env pwsh
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($env:OS -ne "Windows_NT") {
  Write-Error "[error] Bu script sadece Windows icin yazildi."
  exit 1
}

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = $RootDir
$FrontendDir = Join-Path $RootDir "frontend"
$VenvDir = Join-Path $BackendDir ".venv"

$BackendHost = if ($env:BACKEND_HOST) { $env:BACKEND_HOST } else { "127.0.0.1" }
$BackendPort = if ($env:BACKEND_PORT) { [int]$env:BACKEND_PORT } else { 8000 }
$FrontendHost = if ($env:FRONTEND_HOST) { $env:FRONTEND_HOST } else { "127.0.0.1" }
$FrontendPort = if ($env:FRONTEND_PORT) { [int]$env:FRONTEND_PORT } else { 5173 }

$pythonVersionPath = Join-Path $BackendDir ".python-version"
$PythonVersion = if ($env:PYTHON_VERSION) {
  $env:PYTHON_VERSION
} elseif (Test-Path $pythonVersionPath) {
  (Get-Content $pythonVersionPath -TotalCount 1).Trim()
} else {
  "3.12"
}

$env:UV_CACHE_DIR = if ($env:UV_CACHE_DIR) { $env:UV_CACHE_DIR } else { Join-Path $env:TEMP "uv-cache" }
$env:NPM_CONFIG_CACHE = if ($env:NPM_CONFIG_CACHE) { $env:NPM_CONFIG_CACHE } else { Join-Path $env:TEMP "npm-cache" }

function Refresh-Path {
  $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
  $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
  $env:Path = "$machinePath;$userPath"
}

function Test-CommandExists {
  param([Parameter(Mandatory = $true)][string]$Name)
  return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Require-Command {
  param([Parameter(Mandatory = $true)][string]$Name)
  if (-not (Test-CommandExists -Name $Name)) {
    Write-Error "[error] '$Name' bulunamadi."
    exit 1
  }
}

function Ensure-Winget {
  if (-not (Test-CommandExists -Name "winget")) {
    Write-Error "[error] winget bulunamadi. Microsoft App Installer yukleyip tekrar dene."
    exit 1
  }
}

function Ensure-WingetPackage {
  param(
    [Parameter(Mandatory = $true)][string]$PackageId,
    [Parameter(Mandatory = $true)][string]$CommandName,
    [Parameter(Mandatory = $true)][string]$Label
  )

  if (Test-CommandExists -Name $CommandName) {
    Write-Host "[bootstrap] $Label zaten kurulu, skip."
    return
  }

  Ensure-Winget
  Write-Host "[bootstrap] $Label kuruluyor..."
  winget install --id $PackageId -e --scope user --accept-package-agreements --accept-source-agreements
  Refresh-Path

  if (-not (Test-CommandExists -Name $CommandName)) {
    Write-Error "[error] $Label kurulumu tamamlanamadi. Yeni terminal acip tekrar dene."
    exit 1
  }
}

function Test-PortFree {
  param(
    [Parameter(Mandatory = $true)][int]$Port,
    [Parameter(Mandatory = $true)][string]$Name
  )

  $inUse = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  if ($inUse) {
    Write-Error "[error] $Name portu dolu: $Port. BACKEND_PORT/FRONTEND_PORT ile farkli port ver."
    exit 1
  }
}

Ensure-WingetPackage -PackageId "Astral-sh.uv" -CommandName "uv" -Label "uv"
Ensure-WingetPackage -PackageId "OpenJS.NodeJS.LTS" -CommandName "npm" -Label "node/npm"
Require-Command -Name "uv"
Require-Command -Name "npm"

Test-PortFree -Port $BackendPort -Name "backend"
Test-PortFree -Port $FrontendPort -Name "frontend"

Write-Host "[setup] backend virtual env hazirlaniyor..."
New-Item -ItemType Directory -Path $env:UV_CACHE_DIR -Force | Out-Null
New-Item -ItemType Directory -Path $env:NPM_CONFIG_CACHE -Force | Out-Null

Set-Location $BackendDir
Write-Host "[setup] Python $PythonVersion (uv) hazirlaniyor..."
uv python install $PythonVersion
uv venv $VenvDir

$activatePath = Join-Path $VenvDir "Scripts\Activate.ps1"
if (-not (Test-Path $activatePath)) {
  Write-Error "[error] venv activation script bulunamadi: $activatePath"
  exit 1
}

Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force | Out-Null
. $activatePath
uv sync

Write-Host "[setup] frontend bagimliliklari kuruluyor..."
Set-Location $FrontendDir
if (Test-Path (Join-Path $FrontendDir "package-lock.json")) {
  npm ci
} else {
  npm install
}

Write-Host "[build] frontend build aliniyor..."
npm run build

Write-Host "[dev] backend baslatiliyor: http://$BackendHost`:$BackendPort"
$backendProc = Start-Process -FilePath "uv" -ArgumentList @("run", "uvicorn", "main:app", "--host", $BackendHost, "--port", "$BackendPort", "--reload") -WorkingDirectory $BackendDir -PassThru

Write-Host "[dev] frontend baslatiliyor: http://$FrontendHost`:$FrontendPort"
$frontendProc = Start-Process -FilePath "npm" -ArgumentList @("run", "dev", "--", "--host", $FrontendHost, "--port", "$FrontendPort") -WorkingDirectory $FrontendDir -PassThru

Write-Host "[ok] Fullstack dev ortami calisiyor. Cikmak icin Ctrl+C."

try {
  while ($true) {
    if ($backendProc.HasExited -or $frontendProc.HasExited) {
      break
    }
    Start-Sleep -Seconds 1
  }
} finally {
  if (-not $backendProc.HasExited) {
    Stop-Process -Id $backendProc.Id -Force -ErrorAction SilentlyContinue
  }
  if (-not $frontendProc.HasExited) {
    Stop-Process -Id $frontendProc.Id -Force -ErrorAction SilentlyContinue
  }
}

if ($backendProc.HasExited -and $backendProc.ExitCode -ne 0) {
  exit $backendProc.ExitCode
}
if ($frontendProc.HasExited -and $frontendProc.ExitCode -ne 0) {
  exit $frontendProc.ExitCode
}
