<#
.SYNOPSIS
    Bring a second machine fully up to date in one shot: pull the latest repo
    changes, refresh dependencies, wait for Google Drive to finish syncing the
    shared candle folder down locally, then pull those candles into data\.

.DESCRIPTION
    Run this on a machine that already has the repo cloned and has been set up
    at least once before (.venv + .env already exist). It chains three steps
    that otherwise have to be done by hand, in the right order:

      1. git pull --ff-only            (brings down scripts\sync_candles.ps1
                                         itself, plus anything else new)
      2. pip install -r requirements.txt   (picks up any new/changed deps)
      3. poll the Drive folder until its total size stops changing (best-effort
         "cloud download finished" detection - Drive exposes no real signal
         for this), then run scripts\sync_candles.ps1 -Pull

    If this is the FIRST time the app runs on this machine (no .venv yet), it
    falls back to running setup.ps1 instead of a bare pip install.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\update_and_pull_candles.ps1 `
        -DriveFolder "C:\g-jmk\My Drive\_trading_app_candles"

.EXAMPLE
    # Skip the wait-for-stability polling because you already confirmed in
    # File Explorer / the Drive tray icon that the sync is caught up
    powershell -ExecutionPolicy Bypass -File scripts\update_and_pull_candles.ps1 `
        -DriveFolder "C:\g-jmk\My Drive\_trading_app_candles" -NoWait
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$DriveFolder,

    [switch]$NoWait,
    [int]$StableChecks = 3,
    [int]$IntervalSeconds = 20,
    [int]$TimeoutMinutes = 60
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

function Step($msg) { Write-Host ("`n== {0} ==" -f $msg) -ForegroundColor Cyan }

# --- 1. git pull -------------------------------------------------------
Step "git pull"
$branch = (git rev-parse --abbrev-ref HEAD).Trim()
Write-Host "Branch: $branch"

# Only tracked modifications block a pull - untracked scratch files are
# common in this repo and shouldn't stop the update.
$dirty = git status --porcelain | Where-Object { $_ -notmatch '^\?\?' }
if ($dirty) {
    Write-Host "You have local uncommitted changes to tracked files:" -ForegroundColor Yellow
    Write-Host ($dirty -join "`n")
    Write-Host "Stash or commit them before pulling, then re-run this script." -ForegroundColor Red
    exit 1
}

git pull --ff-only
if ($LASTEXITCODE -ne 0) {
    Write-Host "git pull failed (non-fast-forward, network, conflict, or an untracked file would be overwritten)." -ForegroundColor Red
    Write-Host "Resolve manually, then re-run this script." -ForegroundColor Red
    exit 1
}

# --- 2. dependencies -----------------------------------------------------
Step "Refresh dependencies"
$py = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "No .venv found - running full setup.ps1 instead." -ForegroundColor Yellow
    & (Join-Path $ProjectRoot "setup.ps1")
} else {
    & $py -m pip install -r requirements.txt --quiet
    Write-Host "Dependencies up to date."
}

# --- 3. wait for Drive to finish syncing down -----------------------------
if (-not $NoWait) {
    Step "Waiting for Google Drive to finish syncing: $DriveFolder"
    Write-Host "(polling every $IntervalSeconds s, needs $StableChecks stable reads in a row, timeout ${TimeoutMinutes}m)"

    $prevSize = -1
    $stable = 0
    $elapsed = 0
    $ok = $false

    while ($true) {
        if (Test-Path $DriveFolder) {
            $files = Get-ChildItem -Recurse -File $DriveFolder -ErrorAction SilentlyContinue
            $size = ($files | Measure-Object -Property Length -Sum).Sum
            $count = $files.Count
        } else {
            $size = 0
            $count = 0
        }
        $sizeGB = if ($size) { [math]::Round($size / 1GB, 2) } else { 0 }
        Write-Host ("  [{0,4}s] {1,5} files, {2,6} GB" -f $elapsed, $count, $sizeGB)

        if ($size -gt 0 -and $size -eq $prevSize) {
            $stable++
            if ($stable -ge $StableChecks) { $ok = $true; break }
        } else {
            $stable = 0
        }
        $prevSize = $size

        if ($elapsed -ge ($TimeoutMinutes * 60)) { break }
        Start-Sleep -Seconds $IntervalSeconds
        $elapsed += $IntervalSeconds
    }

    if (-not $ok) {
        Write-Host "Gave up waiting after $TimeoutMinutes minutes (or the folder is still empty)." -ForegroundColor Red
        Write-Host "Check the Drive tray icon manually. Once it's idle, re-run with -NoWait." -ForegroundColor Red
        exit 1
    }
    Write-Host "Drive folder size has been stable - proceeding." -ForegroundColor Green
} else {
    Write-Host "`n(-NoWait set - skipping the Drive stability check)" -ForegroundColor DarkGray
}

# --- 4. pull candles into data\ -------------------------------------------
Step "Pull candles into data\"
$syncScript = Join-Path $ProjectRoot "scripts\sync_candles.ps1"
powershell -ExecutionPolicy Bypass -File $syncScript -Pull -DriveFolder $DriveFolder
if ($LASTEXITCODE -ne 0) {
    Write-Host "Candle pull failed - see output above." -ForegroundColor Red
    exit 1
}

Step "Done"
Write-Host "Repo updated, dependencies refreshed, candles pulled." -ForegroundColor Green
Write-Host "Start the app with:  .\run dev" -ForegroundColor Cyan
