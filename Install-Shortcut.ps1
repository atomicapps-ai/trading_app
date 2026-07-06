# Install-Shortcut.ps1
# Creates a pinnable "TradeAgent" shortcut (Desktop + Start menu) that opens the
# TradeAgent Launcher with the app icon — so it runs like a normal Windows app.
#
#   Run once:   right-click this file -> "Run with PowerShell"
#               or:  powershell -ExecutionPolicy Bypass -File Install-Shortcut.ps1
#
# Then right-click the new "TradeAgent" icon and choose "Pin to taskbar".

$ErrorActionPreference = 'Stop'

# Project root = the folder this script lives in.
$root     = Split-Path -Parent $MyInvocation.MyCommand.Definition
$launcher = Join-Path $root 'launcher.py'
$icon     = Join-Path $root 'static\icons\tradeagent.ico'

if (-not (Test-Path $launcher)) { throw "launcher.py not found next to this script ($launcher)" }

# Prefer the project venv's pythonw.exe (windowless — no console flash); fall
# back to whatever pythonw is on PATH.
$pyw = Join-Path $root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $pyw)) { $pyw = 'pythonw.exe' }

$shell = New-Object -ComObject WScript.Shell

$targets = @(
    (Join-Path ([Environment]::GetFolderPath('Desktop'))  'TradeAgent.lnk'),
    (Join-Path ([Environment]::GetFolderPath('Programs')) 'TradeAgent.lnk')
)

foreach ($lnk in $targets) {
    $s = $shell.CreateShortcut($lnk)
    $s.TargetPath       = $pyw
    $s.Arguments        = '"' + $launcher + '"'
    $s.WorkingDirectory = $root
    if (Test-Path $icon) { $s.IconLocation = $icon }
    $s.Description      = 'TradeAgent - start/stop the trading app + Cloudflare tunnel'
    $s.WindowStyle      = 1
    $s.Save()
    Write-Host "Created: $lnk"
}

Write-Host ""
Write-Host "Done. A 'TradeAgent' icon is now on your Desktop and in the Start menu."
Write-Host "To put it on your taskbar: right-click the icon -> 'Pin to taskbar'."
Write-Host "(You can also press the Windows key and type 'TradeAgent' to launch it.)"
