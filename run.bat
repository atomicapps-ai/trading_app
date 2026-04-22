@echo off
cd /d "%~dp0.claude\worktrees\vibrant-heyrovsky-8deb87"
"%~dp0.venv\Scripts\python.exe" -m uvicorn app:app --reload --host 0.0.0.0 --port 5000
