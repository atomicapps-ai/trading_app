# setup.ps1 — one-command bootstrap for a fresh machine (Windows PowerShell).
# Creates the venv, installs ALL dependencies into it, seeds .env, and verifies
# the core imports that have bitten us before (aiosqlite, ib_insync on 3.14).
#
#   .\setup.ps1
#   .\.venv\Scripts\python.exe run.py dev
#
# Always launch the app with .\.venv\Scripts\python.exe (NOT bare `python`,
# which resolves to system Python and won't have the deps).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "== TradeAgent setup ==" -ForegroundColor Cyan

# 1. venv — create if missing
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating .venv ..."
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv .venv }
    else { python -m venv .venv }
}
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
Write-Host "Using: $py"
& $py --version

# 2. dependencies — into the venv
Write-Host "Installing dependencies ..."
& $py -m pip install --upgrade pip | Out-Null
& $py -m pip install -r requirements.txt

# 3. .env — seed from example if absent (never overwrite an existing one)
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Host "Created .env from .env.example — EDIT IT with your creds/ports." -ForegroundColor Yellow
    }
}

# 4. verify the imports that break a half-set-up environment
& $py -c "import aiosqlite, fastapi, uvicorn, pandas, pyarrow, ib_insync; print('core imports OK')"

Write-Host "`nSetup complete." -ForegroundColor Green
Write-Host "Start the app:   .\.venv\Scripts\python.exe run.py dev"
Write-Host "Then open:       http://127.0.0.1:5000"
Write-Host "FVG data (once): .\.venv\Scripts\python.exe -m scripts.fetch_fvg_data"
