@echo off
rem  Double-click this to open the TradeAgent Launcher (Start/Stop control panel).
rem  Uses the project venv's pythonw.exe so no console window appears.
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" "launcher.py"
) else (
  start "" pythonw "launcher.py"
)
