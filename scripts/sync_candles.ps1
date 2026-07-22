<#
.SYNOPSIS
    Push or pull the local candle caches (data\historical, data\fx_hist) to/from
    a Google-Drive-synced folder, so a second machine doesn't have to re-download
    ~2.5GB of bars (yfinance/Alpaca equity CSVs + IBKR FX/gold parquet).

.DESCRIPTION
    data\historical\ and data\fx_hist\ are gitignored — CLAUDE.md/SETUP.md call
    them "regenerable" via yfinance/Alpaca/IBKR, and that's still true. This
    script is a faster path when a second computer's re-fetch would be slow,
    rate-limited, or needs an IB Gateway session you don't want to run twice.

    This is a manual, run-when-you-want-to-sync script — NOT continuous. Google
    Drive's own client does the actual cloud upload/download in the background;
    this script only mirrors between the project's data\ dir and your local
    Drive-synced folder (robocopy /MIR, same pattern as backup_trade_logs.ps1).

    -Push : project data\ -> Drive folder   (run on the machine that HAS the candles)
    -Pull : Drive folder -> project data\   (run on the machine that WANTS them)

    Requires "Google Drive for desktop" in **Mirror** mode (Settings -> Preferences
    -> Google Drive -> "Mirror files"), so there's a real local path to robocopy
    into — NOT "Stream files" only. Default path assumes a Drive mirror at
    "$env:USERPROFILE\My Drive" (same assumption backup_trade_logs.ps1 makes).
    If your machine uses the classic Drive File Stream mount instead, pass
    -DriveFolder "G:\My Drive\TradeAgentBackups\candles" (check your actual
    drive letter in File Explorer).

.EXAMPLE
    # On the machine that already has the candles:
    powershell -ExecutionPolicy Bypass -File scripts\sync_candles.ps1 -Push

.EXAMPLE
    # On the second machine, AFTER Google Drive has finished syncing the
    # candles\ folder down locally (check the Drive tray icon is idle):
    powershell -ExecutionPolicy Bypass -File scripts\sync_candles.ps1 -Pull

.EXAMPLE
    # Preview what would move without copying anything
    powershell -ExecutionPolicy Bypass -File scripts\sync_candles.ps1 -Push -DryRun

.EXAMPLE
    # Also sync the raw HistData FX download cache (rarely needed — it's just
    # an intermediate cache for scripts\fetch_fx_data.py, not read by the app)
    powershell -ExecutionPolicy Bypass -File scripts\sync_candles.ps1 -Push -IncludeRaw
#>
[CmdletBinding(DefaultParameterSetName = 'Push')]
param(
    [Parameter(ParameterSetName = 'Push')]
    [switch]$Push,

    [Parameter(ParameterSetName = 'Pull')]
    [switch]$Pull,

    [string]$DriveFolder = "$env:USERPROFILE\My Drive\TradeAgentBackups\candles",

    [switch]$IncludeRaw,

    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

if (-not $Push -and -not $Pull) {
    Write-Host "Specify -Push (upload local candles to Drive) or -Pull (download from Drive)." -ForegroundColor Red
    exit 1
}

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$DataDir = Join-Path $ProjectRoot 'data'

$CandleDirs = @('historical', 'fx_hist')
if ($IncludeRaw) { $CandleDirs += 'fx_raw' }

$Direction = if ($Push) { 'PUSH (local -> Drive)' } else { 'PULL (Drive -> local)' }

Write-Host "TradeAgent candle sync" -ForegroundColor Cyan
Write-Host ("  Direction: {0}" -f $Direction)
Write-Host ("  Project:   {0}" -f $DataDir)
Write-Host ("  Drive:     {0}" -f $DriveFolder)
if ($DryRun) { Write-Host "  Mode:      DRY RUN (no writes)" -ForegroundColor Yellow }
Write-Host ("-" * 60)

if ($Pull -and -not (Test-Path $DriveFolder)) {
    Write-Host "Drive folder not found: $DriveFolder" -ForegroundColor Red
    Write-Host "Make sure Google Drive has finished syncing it down to this machine first," -ForegroundColor Red
    Write-Host "and that -DriveFolder points at your actual Drive mirror/mount path." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $DriveFolder)) {
    if ($DryRun) {
        Write-Host "Would create $DriveFolder" -ForegroundColor Yellow
    } else {
        New-Item -ItemType Directory -Path $DriveFolder -Force | Out-Null
        Write-Host "Created $DriveFolder"
    }
}

foreach ($name in $CandleDirs) {
    $localPath = Join-Path $DataDir $name
    $drivePath = Join-Path $DriveFolder $name

    if ($Push) {
        $src = $localPath; $dst = $drivePath
    } else {
        $src = $drivePath; $dst = $localPath
    }

    if (-not (Test-Path $src)) {
        Write-Host ("[skip] {0,-12} (source missing: {1})" -f $name, $src) -ForegroundColor DarkGray
        continue
    }

    if ($DryRun) {
        $fileCount = (Get-ChildItem -Recurse -File $src -ErrorAction SilentlyContinue).Count
        $size = (Get-ChildItem -Recurse -File $src -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
        $sizeGB = if ($size) { [math]::Round($size / 1GB, 2) } else { 0 }
        Write-Host ("[plan] {0,-12} {1} files, {2} GB" -f $name, $fileCount, $sizeGB) -ForegroundColor Yellow
        continue
    }

    $robocopyArgs = @(
        $src, $dst,
        '/MIR',
        '/R:2', '/W:1',
        '/NP', '/NDL', '/NJH', '/NJS'
    )
    robocopy @robocopyArgs | Out-Null
    $ec = $LASTEXITCODE
    if ($ec -ge 8) {
        Write-Host ("[FAIL] {0,-12} robocopy exit {1}" -f $name, $ec) -ForegroundColor Red
    } else {
        Write-Host ("[ok]   {0,-12} (robocopy exit {1})" -f $name, $ec) -ForegroundColor Green
    }
}

Write-Host ("-" * 60)
Write-Host "Sync complete." -ForegroundColor Cyan
if ($Push) {
    Write-Host "Reminder: this only mirrors into your LOCAL Drive folder - actual" -ForegroundColor DarkGray
    Write-Host "cloud upload happens in the background via the Google Drive client." -ForegroundColor DarkGray
    Write-Host "Check the Drive tray icon is idle before pulling on the other machine." -ForegroundColor DarkGray
} else {
    Write-Host "Restart the app if it was already running so data_service picks up" -ForegroundColor DarkGray
    Write-Host "the new cached bars." -ForegroundColor DarkGray
}
