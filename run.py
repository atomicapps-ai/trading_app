"""
run.py - start the TradeAgent server.

Usage:
    python run.py dev    (hot reload, info logging)
    python run.py prod   (no reload, 2 workers)
"""
import subprocess
import sys

mode = sys.argv[1].lower() if len(sys.argv) > 1 else "dev"

if mode not in ("dev", "prod"):
    print(f"Unknown mode '{mode}'. Use: dev | prod")
    sys.exit(1)

base = [sys.executable, "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "5000"]

if mode == "dev":
    cmd = base + ["--reload", "--log-level", "info"]
    print("TradeAgent DEV (hot reload) -> http://localhost:5000")
else:
    cmd = base + ["--workers", "2", "--log-level", "warning"]
    print("TradeAgent PROD -> http://localhost:5000")

subprocess.run(cmd)
