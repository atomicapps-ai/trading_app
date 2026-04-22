# Start-Server.ps1 — run from project root or double-click in Explorer
# Starts the TradeAgent server on http://localhost:5000

$branch = "vibrant-heyrovsky-8deb87"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$worktree = Join-Path $root ".claude\worktrees\$branch"
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $worktree)) {
    Write-Host "Worktree not found: $worktree" -ForegroundColor Red
    exit 1
}

Write-Host "Starting TradeAgent on http://localhost:5000 ..." -ForegroundColor Cyan
Set-Location $worktree
& $python -m uvicorn app:app --reload --host 0.0.0.0 --port 5000
