"""scripts/fetch_earnings_history.py — fetch historical earnings dates
for every symbol in a screener and persist to a single CSV.

Source: yfinance Ticker.get_earnings_dates(limit=N). yfinance returns the
"Earnings Date" indexed in US/Eastern with the announcement timestamp
(e.g. 06:00 ET = before-market, 16:00 ET = after-market). We carry the
full timestamp through so downstream filters can decide which session the
print actually affected.

Output: data/earnings_history.csv with columns:
    symbol, earnings_ts (ISO with tz), eps_estimate, reported_eps, surprise_pct
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import yfinance as yf  # noqa: E402

from services import universe_service  # noqa: E402

OUT_PATH = ROOT / "data" / "earnings_history.csv"


async def _resolve_symbols(screener: str) -> list[str]:
    preset = await universe_service.get_preset_db(screener)
    if preset is None:
        raise SystemExit(f"screener {screener!r} not found")
    return list(preset.get("tickers") or [])


def fetch_one(symbol: str, limit: int = 40) -> pd.DataFrame:
    t = yf.Ticker(symbol)
    df = t.get_earnings_dates(limit=limit)
    if df is None or df.empty:
        return pd.DataFrame()
    out = pd.DataFrame({
        "symbol": symbol.upper(),
        "earnings_ts": df.index,
        "eps_estimate": df.get("EPS Estimate"),
        "reported_eps": df.get("Reported EPS"),
        "surprise_pct": df.get("Surprise(%)"),
    })
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--screener", default="core_universe")
    ap.add_argument("--limit", type=int, default=40,
                    help="quarters of history per symbol (yfinance caps at ~50)")
    args = ap.parse_args()

    symbols = await _resolve_symbols(args.screener)
    print(f"fetching earnings dates for {len(symbols)} symbols (limit={args.limit})...")

    chunks: list[pd.DataFrame] = []
    t0 = time.time()
    for i, sym in enumerate(symbols, 1):
        try:
            chunk = fetch_one(sym, limit=args.limit)
        except Exception as e:
            print(f"  [{i:>3d}/{len(symbols)}] {sym:<6s} FAIL  {e}")
            continue
        if chunk.empty:
            print(f"  [{i:>3d}/{len(symbols)}] {sym:<6s} no data")
            continue
        chunks.append(chunk)
        print(f"  [{i:>3d}/{len(symbols)}] {sym:<6s} {len(chunk)} rows  "
              f"({chunk['earnings_ts'].min().date()} -> {chunk['earnings_ts'].max().date()})")

    if not chunks:
        print("no earnings data fetched")
        return 1

    out = pd.concat(chunks, ignore_index=True)
    out["earnings_ts"] = pd.to_datetime(out["earnings_ts"], utc=True)
    out = out.sort_values(["symbol", "earnings_ts"]).reset_index(drop=True)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_PATH, index=False)

    elapsed = time.time() - t0
    print(f"\nDONE — {len(out):,} earnings rows across {out['symbol'].nunique()} "
          f"symbols in {elapsed:.0f}s")
    print(f"  saved: {OUT_PATH}")
    print(f"  range: {out['earnings_ts'].min().date()} -> {out['earnings_ts'].max().date()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
