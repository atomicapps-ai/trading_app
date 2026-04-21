<#
.SYNOPSIS
    Back up trade_logs/ (and a small set of per-machine config) to a
    cloud-synced folder so the ML data pool survives laptop deaths and
    moves between machines.

.DESCRIPTION
    Mirrors the project's `trade_logs\` directory into a Drive-synced
    folder, then copies `.env` and `settings.yaml` alongside it so a
    fresh machine can be bootstrapped from git + this backup.

    Gitignored items that are NOT backed up (intentional): `.venv\`,
    `data\historical\`, `data\news_cache\`, `data\edgar_cache\`,
    `data\sentiment_cache\`, `data\claude_trading_app.db`. Those are
    all regenerable — see CLAUDE.md storage table.

    Uses robocopy with /MIR so deleted/aged files on the source are
    reflected in the destination. If you WANT history, use a git repo
    for trade_logs instead (Phase 7 discussion).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\backup_trade_logs.ps1

.EXAMPLE
    # Override the destination (e.g. another cloud provider)
    powershell -ExecutionPolicy Bypass -File scripts\backup_trade_logs.ps1 `
        -Destination "D:\OneDrive\TradeAgentBackups"
#>
[CmdletBinding()]
param(
    [string]$Destination = "$env:USERPROFILE\My Drive\TradeAgentBackups",
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

# Project root = parent of this script file.
$ProjectRoot = Split-Path -Parent $PSScriptRoot

$Sources = @(
    @{ Name = 'trade_logs';   Path = Join-Path $ProjectRoot 'trade_logs' },
    @{ Name = 'strategy_configs'; Path = Join-Path $ProjectRoot 'strategy_configs' },
    @{ Name = 'universe_filters'; Path = Join-Path $ProjectRoot 'universe_filters' }
)

# Single files to copy (secrets + per-machine config).
$Files = @(
    @{ Name = '.env';          Path = Join-Path $ProjectRoot '.env' },
    @{ Name = 'settings.yaml'; Path = Join-Path $ProjectRoot 'settings.yaml' }
)

Write-Host "TradeAgent backup" -ForegroundColor Cyan
Write-Host ("  Project:     {0}" -f $ProjectRoot)
Write-Host ("  Destination: {0}" -f $Destination)
if ($DryRun) {
    Write-Host "  Mode:        DRY RUN (no writes)" -ForegroundColor Yellow
}
Write-Host ("-" * 60)

if (-not (Test-Path $Destination)) {
    if ($DryRun) {
        Write-Host "Would create $Destination" -ForegroundColor Yellow
    } else {
        New-Item -ItemType Directory -Path $Destination -Force | Out-Null
        Write-Host "Created $Destination"
    }
}

# --- Directories via robocopy (MIR keeps the dest synced) ------------------
foreach ($src in $Sources) {
    $dst = Join-Path $Destination $src.Name
    if (-not (Test-Path $src.Path)) {
        Write-Host ("[skip] {0,-20} (source missing)" -f $src.Name) -ForegroundColor DarkGray
        continue
    }
    if ($DryRun) {
        $fileCount = (Get-ChildItem -Recurse -File $src.Path -ErrorAction SilentlyContinue).Count
        Write-Host ("[plan] {0,-20} {1} files" -f $src.Name, $fileCount) -ForegroundColor Yellow
        continue
    }

    $args = @(
        $src.Path,
        $dst,
        '/MIR',         # mirror (copies + deletes)
        '/R:2',         # retry count
        '/W:1',         # wait between retries (sec)
        '/NP',          # no progress (cleaner logs)
        '/NDL',         # no directory list
        '/NJH', '/NJS'  # no job header / summary
    )
    robocopy @args | Out-Null
    # robocopy exit codes: 0-7 are success variants, >= 8 is a real failure
    $ec = $LASTEXITCODE
    if ($ec -ge 8) {
        Write-Host ("[FAIL] {0,-20} robocopy exit {1}" -f $src.Name, $ec) -ForegroundColor Red
    } else {
        Write-Host ("[ok]   {0,-20} (robocopy exit {1})" -f $src.Name, $ec) -ForegroundColor Green
    }
}

# --- Single files ---------------------------------------------------------
foreach ($f in $Files) {
    if (-not (Test-Path $f.Path)) {
        Write-Host ("[skip] {0,-20} (source missing)" -f $f.Name) -ForegroundColor DarkGray
        continue
    }
    $dst = Join-Path $Destination $f.Name
    if ($DryRun) {
        Write-Host ("[plan] {0,-20} -> {1}" -f $f.Name, $dst) -ForegroundColor Yellow
    } else {
        Copy-Item -Path $f.Path -Destination $dst -Force
        Write-Host ("[ok]   {0,-20}" -f $f.Name) -ForegroundColor Green
    }
}

Write-Host ("-" * 60)
Write-Host "Backup complete." -ForegroundColor Cyan
Write-Host "Reminder: the backup includes .env (broker credentials)."
Write-Host "         Make sure the Drive folder is NOT shared with anyone else."
