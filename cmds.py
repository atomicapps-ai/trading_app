"""
Run this file to execute the opening candle pattern scanner.
Results will be written to claude_output.txt in this folder.
"""
import subprocess, sys

subprocess.run(
    [sys.executable, "scripts/scan_opening_patterns.py"],
    check=True,
)