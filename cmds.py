"""
Run this file to execute the Strategy 2 (Double Lock) Python backtest.
Results are written to claude_output.txt in this folder.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT  = ROOT / "claude_output.txt"

import os
env = dict(os.environ)
env["PYTHONIOENCODING"] = "utf-8"

with OUT.open("w", encoding="utf-8") as fh:
    proc = subprocess.run(
        [sys.executable, "scripts/smoke_intraday_pipeline.py"],
        cwd=ROOT,
        stdout=fh,
        stderr=subprocess.STDOUT,
        env=env,
    )

print(f"Exit code: {proc.returncode}")
print(f"Output written to: {OUT}")
