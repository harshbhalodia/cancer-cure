#requires -Version 5.1
# One-time setup: backend venv + dependencies, frontend dependencies.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$web = Join-Path $root "apps\web"

if (-not (Test-Path "$backend\.venv")) { py -3 -m venv "$backend\.venv" }
& "$backend\.venv\Scripts\python.exe" -m pip install -q -r "$backend\requirements.txt"
Push-Location $web
npm install
Pop-Location
Write-Host "Setup complete. Run .\scripts\start.ps1" -ForegroundColor Green
