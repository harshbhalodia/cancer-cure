#requires -Version 5.1
# Starts the API (http://localhost:8100) in a new window and the web app (http://localhost:5174) here.
# Requires LM Studio's local server on http://localhost:1234 with the configured model loaded.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$web = Join-Path $root "apps\web"

Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "& '$backend\.venv\Scripts\python.exe' -m uvicorn app.main:app --reload --port 8100 --app-dir '$backend'"
)
Push-Location $web
npm run dev
Pop-Location
