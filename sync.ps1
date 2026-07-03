# sync.ps1 — bring this machine up to date with origin/main and make it runnable.
# Save/keep in the repo root, run:  .\sync.ps1
# Works from any clone path (it locates itself). Leaves .env / settings.yaml /
# data caches untouched (all gitignored) — only code + deps are synced.
$ErrorActionPreference = "Stop"

# Use the script's own folder when run as a saved .ps1; otherwise fall back to
# the current directory (e.g. when the content is pasted into the console,
# $PSScriptRoot is empty). Then sanity-check we're actually in the repo.
$root = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
Set-Location $root
if (-not (Test-Path ".git")) {
    Write-Host "Not a git repo here. Save this as sync.ps1 in the repo root, or cd into the repo first." -ForegroundColor Red
    exit 1
}

Write-Host "== Syncing to origin/main ==" -ForegroundColor Cyan

# 1. Fetch latest
git fetch origin --prune

# 2. Stash local tracked changes so the switch/pull can't be blocked
$dirty = git status --porcelain --untracked-files=no
if ($dirty) {
    Write-Host "Stashing local tracked changes (restore later: git stash pop)" -ForegroundColor Yellow
    git stash push -m "sync.ps1 auto-stash"
}

# 3. Move to main and fast-forward to origin/main
git checkout main 2>$null
if ($LASTEXITCODE -ne 0) { git checkout -b main --track origin/main }
git pull --ff-only origin main

# 4. Ensure a venv, then refresh dependencies (picks up anything new on main)
$py = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Creating .venv ..."
    if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv .venv } else { python -m venv .venv }
}
& $py -m pip install --upgrade pip | Out-Null
& $py -m pip install -r requirements.txt

# 5. Seed .env on a fresh machine (never overwrites an existing one)
if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from example - set BROKER_PROVIDER=ibkr and IBKR_PORT=4002." -ForegroundColor Yellow
}

# 6. Verify the imports that break a half-set-up env, and show where we landed
& $py -c "import aiosqlite, fastapi, uvicorn, pandas, pyarrow, ib_insync; print('core imports OK')"
Write-Host "Now at: " -NoNewline; git log --oneline -1

Write-Host "`nSynced. Start the app:  .\.venv\Scripts\python.exe run.py dev" -ForegroundColor Green
