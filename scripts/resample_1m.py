"""resample_1m — derive coarser bars (5m/15m/30m/1h/daily) from the 1-min Parquet store.

The 1-min files (data/historical_1m/<SYM>.parquet, from fetch_alphavantage.py) are the single
source of truth; everything else is resampled from them. Writes canonical CSVs
(datetime,Open,High,Low,Close,Volume) into data/historical/ so all existing backtests just work.

  python scripts/resample_1m.py --symbols SPY QQQ --intervals 5m,30m,1d
  python scripts/resample_1m.py --all --intervals 5m,30m,1d

Note: 1-min bars are UTC and RTH-only, so resampling on the UTC clock aligns correctly to ET
session boundaries (ET is a whole-hour offset, so :00/:30 UTC == :00/:30 ET).
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "historical_1m"
HIST = ROOT / "data" / "historical"
HIST.mkdir(parents=True, exist_ok=True)
RULE = {"1m": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "60min", "1d": "1D"}
AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


def load_1m(symbol: str) -> pd.DataFrame | None:
    p = SRC / f"{symbol}.parquet"
    return pd.read_parquet(p) if p.exists() else None


def resample(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    if interval == "1m":
        return df.copy()
    if interval == "1d":
        # Group by ET trading date (avoids UTC-midnight splits); bar-stamp at 00:00 UTC of that date.
        et = df.tz_convert("America/New_York")
        g = et.groupby(et.index.normalize().tz_convert("UTC")).agg(AGG).dropna(subset=["open"])
        return g
    return df.resample(RULE[interval], label="left", closed="left").agg(AGG).dropna(subset=["open"])


def write_csv(df: pd.DataFrame, symbol: str, interval: str) -> int:
    out = df.copy()
    out.columns = [c.capitalize() for c in out.columns]
    out.index.name = "datetime"
    (HIST / f"{symbol}_{interval}.csv").write_text(out.to_csv())
    return len(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--intervals", default="5m,30m,1d")
    args = ap.parse_args()
    intervals = [x.strip() for x in args.intervals.split(",") if x.strip()]
    syms = args.symbols or ([p.stem for p in SRC.glob("*.parquet")] if args.all else None)
    if not syms:
        sys.exit("give --symbols S1 S2 ... or --all")
    for s in syms:
        df = load_1m(s)
        if df is None or df.empty:
            print(f"{s}: no 1-min parquet — skip"); continue
        for iv in intervals:
            n = write_csv(resample(df, iv), s, iv)
            print(f"{s} {iv}: {n} rows  [{df.index.min().date()} .. {df.index.max().date()}]")


if __name__ == "__main__":
    main()
