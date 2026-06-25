"""scripts/fetch_corporate_actions.py — fetch split + dividend history
for every symbol in a screener and persist to one CSV.

Source: yfinance Ticker.splits / Ticker.dividends.

Output: data/corporate_actions.csv with columns:
    symbol, date (YYYY-MM-DD), kind ("split"|"dividend"), value
where:
    - split rows hold the split ratio (e.g. 4.0 = 4-for-1)
    - dividend rows hold the cash amount per share

The downstream filter in find_explosive_first_hour.py uses this to mask
GAP triggers on ex-split / ex-dividend days (Alpaca raw prices show those
as huge "gaps" when in reality nothing happened).
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

OUT_PATH = ROOT / "data" / "corporate_actions.csv"


async def _resolve_symbols(screener: str) -> list[str]:
    preset = await universe_service.get_preset_db(screener)
    if preset is None:
        raise SystemExit(f"screener {screener!r} not found")
    return list(preset.get("tickers") or [])


def fetch_one(symbol: str) -> pd.DataFrame:
    t = yf.Ticker(symbol)
    rows: list[dict] = []
    try:
        splits = t.splits
        if splits is not None and not splits.empty:
            for ts, val in splits.items():
                rows.append({
                    "symbol": symbol.upper(),
                    "date": pd.Timestamp(ts).strftime("%Y-%m-%d"),
                    "kind": "split",
                    "value": float(val),
                })
    except Exception as e:
        print(f"  splits failed for {symbol}: {e}")

    try:
        divs = t.dividends
        if divs is not None and not divs.empty:
            for ts, val in divs.items():
                rows.append({
                    "symbol": symbol.upper(),
                    "date": pd.Timestamp(ts).strftime("%Y-%m-%d"),
                    "kind": "dividend",
                    "value": float(val),
                })
    except Exception as e:
        print(f"  dividends failed for {symbol}: {e}")

    return pd.DataFrame(rows)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--screener", default="core_universe_100")
    args = ap.parse_args()

    symbols = await _resolve_symbols(args.screener)
    print(f"fetching corporate actions for {len(symbols)} symbols...")

    chunks: list[pd.DataFrame] = []
    t0 = time.time()
    for i, sym in enumerate(symbols, 1):
        chunk = fetch_one(sym)
        if chunk.empty:
            print(f"  [{i:>3d}/{len(symbols)}] {sym:<6s} no data")
            continue
        n_splits = (chunk["kind"] == "split").sum()
        n_divs   = (chunk["kind"] == "dividend").sum()
        chunks.append(chunk)
        print(f"  [{i:>3d}/{len(symbols)}] {sym:<6s} splits={n_splits:>2d}  divs={n_divs:>3d}")

    if not chunks:
        print("no data fetched")
        return 1

    out = pd.concat(chunks, ignore_index=True)
    out = out.sort_values(["symbol", "date", "kind"]).reset_index(drop=True)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_PATH, index=False)

    elapsed = time.time() - t0
    n_sym = out["symbol"].nunique()
    n_split = (out["kind"] == "split").sum()
    n_div = (out["kind"] == "dividend").sum()
    print(f"\nDONE — {n_split:,} splits + {n_div:,} dividends across {n_sym} symbols "
          f"in {elapsed:.0f}s")
    print(f"  saved: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
