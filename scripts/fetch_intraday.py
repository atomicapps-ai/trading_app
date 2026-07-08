"""fetch_intraday — pull 1m/5m intraday bars (Alpaca SIP) for liquid names into data/historical.

Track A of the day-trade edge hunt: get finer-resolution data than the 30m we had, plus the ETFs
that were missing (SPY/QQQ/IWM/DIA), so intraday tests are fair.

  python scripts/fetch_intraday.py                 # default set, 5m (full) + 1m (recent)
  python scripts/fetch_intraday.py --symbols SPY QQQ --intervals 5m,1m --start 2021-01-01

Saves canonical CSVs (datetime,Open,High,Low,Close,Volume) matching strategy_suite.load / the app.
1m is fetched year-by-year (Alpaca paginates) and concatenated. Skips a file that already exists
unless --force.
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
from services.hf_data_service import _fetch_symbol_alpaca_sync  # noqa: E402

HIST = ROOT / "data" / "historical"
HIST.mkdir(parents=True, exist_ok=True)

ETFS = ["SPY", "QQQ", "IWM", "DIA"]
STOCKS = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "TSLA", "GOOGL", "AMD", "NFLX", "AVGO"]
# 1m over many years is huge; default to a solid recent window. 5m gets the longer history.
DEFAULT_1M_START = "2023-01-01"
DEFAULT_5M_START = "2021-01-01"


def _save(df: pd.DataFrame, sym: str, interval: str) -> int:
    if df is None or df.empty:
        return 0
    out = df.copy()
    out.columns = [c.capitalize() for c in out.columns]
    out.index.name = "datetime"
    (HIST / f"{sym}_{interval}.csv").write_text(out.to_csv())
    return len(out)


def _fetch_span(sym: str, interval: str, start: str, end: str | None) -> pd.DataFrame:
    """1m year-by-year to stay under pagination limits; others in one shot."""
    if interval != "1m":
        return _fetch_symbol_alpaca_sync(sym, start, end, interval)
    frames = []
    y0 = int(start[:4]); y1 = (int(end[:4]) if end else pd.Timestamp.utcnow().year)
    for y in range(y0, y1 + 1):
        s = f"{max(y, y0)}-01-01"; e = f"{y}-12-31"
        try:
            frames.append(_fetch_symbol_alpaca_sync(sym, s, e, "1m"))
        except Exception as exc:  # noqa: BLE001
            print(f"    {sym} 1m {y}: {repr(exc)[:120]}")
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames).sort_index()[~pd.concat(frames).sort_index().index.duplicated()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*", default=ETFS + STOCKS)
    ap.add_argument("--intervals", default="5m,1m")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    intervals = [x.strip() for x in args.intervals.split(",") if x.strip()]

    for sym in args.symbols:
        for iv in intervals:
            p = HIST / f"{sym}_{iv}.csv"
            if p.exists() and not args.force:
                print(f"{sym} {iv}: exists ({sum(1 for _ in open(p))-1} rows) — skip")
                continue
            start = args.start or (DEFAULT_1M_START if iv == "1m" else DEFAULT_5M_START)
            try:
                df = _fetch_span(sym, iv, start, args.end)
                n = _save(df, sym, iv)
                span = f"{df.index.min()} -> {df.index.max()}" if n else "empty"
                print(f"{sym} {iv}: {n} rows  {span}")
            except Exception as exc:  # noqa: BLE001
                print(f"{sym} {iv}: ERROR {repr(exc)[:160]}")


if __name__ == "__main__":
    main()
