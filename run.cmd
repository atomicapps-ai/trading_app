@echo off
rem TradeAgent launcher (Windows). Usage from the project folder:
rem     run dev            (cmd.exe)
rem     .\run dev          (PowerShell — needs the .\ prefix)
rem     run prod --port 8080
rem Always uses the project's venv python, so you never type the full path
rem or need the venv activated. %~dp0 is this script's own folder.
"%~dp0.venv\Scripts\python.exe" "%~dp0run.py" %*
