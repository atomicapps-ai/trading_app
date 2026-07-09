# Watchdog: keep resuming the Alpha Vantage 20yr pull until all symbols are complete.
# Each python invocation skips already-saved symbols, so re-running = eventual completion
# even across crashes / network drops. Logs to data\av_pull_liquid100b.log (appended).
$ErrorActionPreference = "Continue"
Set-Location "C:\Projects\trading_app"
$py  = ".\.venv\Scripts\python.exe"
$log = "data\av_pull_liquid100b.log"
$target = 102
for ($i = 1; $i -le 60; $i++) {
    $done = (Get-ChildItem "data\historical_1m\*.parquet" -ErrorAction SilentlyContinue).Count
    if ($done -ge $target) { "WATCHDOG: all $done symbols complete - done" | Out-File $log -Append; break }
    "WATCHDOG: attempt $i, $done/$target complete, (re)launching pull $(Get-Date -Format 'u')" | Out-File $log -Append
    & $py -u "scripts\fetch_alphavantage.py" --universe liquid100 --start 2005-01 --rpm 75 *>> $log
    Start-Sleep -Seconds 15
}
