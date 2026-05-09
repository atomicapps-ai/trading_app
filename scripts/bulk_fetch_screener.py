"""scripts/bulk_fetch_screener.py — fetch daily bars for every ticker in a
named screener, skipping anything already cached locally.

Uses the existing hf_data_service (HF stocks-daily for stocks, yfinance
auto-fallback for ETFs). Sequential per symbol.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")                            # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from services import hf_data_service, universe_service


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--screener", required=True)
    ap.add_argument("--source", default="auto",
                    choices=["auto", "hf", "yfinance", "alpaca"])
    ap.add_argument("--start", default="2010-01-01")
    ap.add_argument("--interval", default="1d")
    ap.add_argument("--skip-existing", action="store_true", default=True)
    ap.add_argument("--no-skip-existing", dest="skip_existing", action="store_false")
    args = ap.parse_args()

    preset = await universe_service.get_preset_db(args.screener)
    if preset is None:
        print(f"screener {args.screener!r} not found")
        return 1
    tickers = preset.get("tickers", []) or []
    if not tickers:
        print(f"screener {args.screener!r} has no tickers — run the screener first")
        return 1

    hist_dir = ROOT / "data" / "historical"
    hist_dir.mkdir(parents=True, exist_ok=True)

    todo: list[str] = []
    for sym in tickers:
        path = hist_dir / f"{sym.upper()}_{args.interval}.csv"
        if args.skip_existing and path.exists():
            continue
        todo.append(sym)

    print(f"screener: {args.screener}  total tickers: {len(tickers)}")
    print(f"already cached: {len(tickers) - len(todo)}  to fetch: {len(todo)}")
    print(f"source={args.source}  interval={args.interval}  start={args.start}")
    print("-" * 78)

    t0 = time.time()
    ok_count = 0
    err_count = 0
    for i, sym in enumerate(todo, 1):
        ts = time.time()
        result = await hf_data_service.fetch_and_save(
            sym, source=args.source, start=args.start, interval=args.interval,
        )
        dur = time.time() - ts
        if result["ok"]:
            ok_count += 1
            print(f"[{i:>3d}/{len(todo)}] {sym:<6s} ok  "
                  f"{result['rows']:>5d} rows  {result['source']:<22s} "
                  f"({dur:.1f}s)")
        else:
            err_count += 1
            print(f"[{i:>3d}/{len(todo)}] {sym:<6s} FAIL  "
                  f"{result.get('error', '?'):<60s} ({dur:.1f}s)")

    elapsed = time.time() - t0
    print("-" * 78)
    print(f"DONE — {ok_count} ok, {err_count} failed, {elapsed:.0f}s "
          f"({elapsed / max(len(todo), 1):.1f}s avg)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
