"""Bulk-fetch bellwether-16 at 30m via Alpaca and save to data/historical/.

Run-once helper triggered after wiring the Alpaca source on the Data Fetch
page. Sequential fetch (Alpaca's free tier rate-limits parallel calls).
Prints a per-symbol status line so you can watch progress.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

# Force UTF-8 stdout so the arrow character below survives Windows cp1252.
try:
    sys.stdout.reconfigure(encoding="utf-8")                            # type: ignore[attr-defined]
except Exception:
    pass

# Make sure dotenv runs before importing the service so ALPACA_* keys are set.
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=False)
sys.path.insert(0, str(ROOT))

from services import hf_data_service                                     # noqa: E402

BELLWETHER_16 = [
    "AAPL", "AMD", "AMZN", "BA", "COST", "GS", "HD", "INTC",
    "IWM", "META", "MSFT", "NVDA", "ORCL", "SPY", "TSLA", "XLF",
]


async def main() -> int:
    start = "2022-01-01"
    interval = "30m"
    print(f"bulk fetch: {len(BELLWETHER_16)} symbols × {interval} from {start}")
    print("-" * 70)
    rc = 0
    t0 = time.time()
    for i, sym in enumerate(BELLWETHER_16, 1):
        ts = time.time()
        result = await hf_data_service.fetch_and_save(
            sym, source="alpaca", start=start, interval=interval
        )
        elapsed = time.time() - ts
        if result["ok"]:
            print(
                f"[{i:2d}/{len(BELLWETHER_16)}] {sym:5s}  ok  "
                f"{result['rows']:>6,} rows  "
                f"{result['first']} -> {result['last']}  "
                f"{result['size_kb']:>7.1f} KB  ({elapsed:.1f}s)"
            )
        else:
            rc = 1
            print(
                f"[{i:2d}/{len(BELLWETHER_16)}] {sym:5s}  FAIL  "
                f"{result['error']}  ({elapsed:.1f}s)"
            )
    print("-" * 70)
    print(f"total elapsed: {time.time() - t0:.1f}s  exit={rc}")
    return rc


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
