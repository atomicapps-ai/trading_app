"""fetch_alphavantage — pull deep 1-minute history from Alpha Vantage (month-sliced), resumable.

Each API call returns ONE month of 1-min bars for ONE symbol (TIME_SERIES_INTRADAY, month=YYYY-MM,
outputsize=full). We store each symbol's 1-min bars as a single Parquet file and resume by skipping
months already present — so a dropped run continues where it left off.

Setup:
  1. Put your key in .env:            ALPHAVANTAGE_API_KEY=your_key_here
     (optional, premium tier rate):  ALPHAVANTAGE_RPM=75      # $50 tier = 75/min; free ~5/min
  2. Validate free (SPY/QQQ, 2 months):
       python scripts/fetch_alphavantage.py --symbols SPY QQQ --start 2026-04 --rpm 5
  3. Full 20-year pull on premium (liquid universe):
       python scripts/fetch_alphavantage.py --universe liquid100 --start 2005-01 --rpm 75

Output: data/historical_1m/<SYM>.parquet  (index=UTC datetime, cols open/high/low/close/volume).
Derive 5m/30m/daily with scripts/resample_1m.py.
"""
from __future__ import annotations
import argparse, io, os, sys, time
from datetime import date
from pathlib import Path
import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
OUT = ROOT / "data" / "historical_1m"
OUT.mkdir(parents=True, exist_ok=True)
BASE = "https://www.alphavantage.co/query"

LIQUID100 = [
    "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLU", "XLB", "XLRE", "XLC",
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "TSLA", "GOOGL", "GOOG", "AVGO", "AMD", "NFLX", "ADBE", "CRM",
    "COST", "PEP", "KO", "WMT", "HD", "MCD", "NKE", "SBUX", "JPM", "BAC", "WFC", "GS", "MS", "C", "V", "MA",
    "AXP", "BRK-B", "UNH", "JNJ", "LLY", "PFE", "MRK", "ABBV", "TMO", "ABT", "XOM", "CVX", "COP", "SLB",
    "CAT", "BA", "GE", "HON", "UPS", "LMT", "DE", "PG", "CL", "MDLZ", "T", "VZ", "TMUS", "DIS", "CMCSA",
    "ORCL", "CSCO", "INTC", "QCOM", "TXN", "IBM", "NOW", "INTU", "MU", "AMAT", "PYPL", "SQ", "SHOP", "UBER",
    "F", "GM", "PLTR", "SOFI", "COIN", "MARA", "RIOT", "SMH", "ARKK", "TLT", "GLD", "SLV", "USO", "EEM", "HYG",
]


def _months(start: str, end: str | None):
    y, m = int(start[:4]), int(start[5:7])
    e = date.today() if not end else date(int(end[:4]), int(end[5:7]), 1)
    while (y, m) <= (e.year, e.month):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m > 12:
            m = 1; y += 1


def _existing_months(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        idx = pd.read_parquet(path, columns=[]).index
        return {f"{t.year:04d}-{t.month:02d}" for t in idx}
    except Exception:
        return set()


def _fetch_month(sym: str, month: str, key: str) -> pd.DataFrame | None:
    api_sym = sym.replace("-", ".")     # BRK-B -> BRK.B
    params = {
        "function": "TIME_SERIES_INTRADAY", "symbol": api_sym, "interval": "1min",
        "month": month, "outputsize": "full", "extended_hours": "false",
        "adjusted": "true", "datatype": "csv", "apikey": key,
    }
    txt = None
    for net_try in range(5):
        try:
            r = requests.get(BASE, params=params, timeout=90)
            txt = r.text
            break
        except requests.exceptions.RequestException:
            time.sleep(5 * (net_try + 1))   # transient network blip — back off and retry
    if txt is None:
        return None                          # all retries failed; caller logs + moves on (self-heals on resume)
    if not txt or txt[:1] in ("{", "<") or "Error" in txt[:200] or "Note" in txt[:200] or "higher API call" in txt or "premium" in txt[:300].lower():
        return ("RATELIMIT" if ("Note" in txt or "higher API call" in txt or "premium" in txt.lower()) else None)  # type: ignore
    try:
        df = pd.read_csv(io.StringIO(txt))
    except Exception:
        return None
    if df.empty or "timestamp" not in df.columns:
        return pd.DataFrame()   # month with no data
    df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize("America/New_York").dt.tz_convert("UTC")
    df = df.rename(columns={"timestamp": "datetime"}).set_index("datetime").sort_index()
    return df[["open", "high", "low", "close", "volume"]]


def run(symbols, start, end, rpm, key):
    delay = 60.0 / max(rpm, 1)
    for sym in symbols:
        path = OUT / f"{sym}.parquet"
        have = _existing_months(path)
        todo = [mo for mo in _months(start, end) if mo not in have]
        if not todo:
            print(f"{sym}: complete ({len(have)} months) — skip"); continue
        frames = [pd.read_parquet(path)] if path.exists() else []
        got = 0
        for mo in todo:
            for attempt in range(4):
                res = _fetch_month(sym, mo, key)
                if isinstance(res, str) and res == "RATELIMIT":
                    print(f"  {sym} {mo}: rate-limited, backing off {30*(attempt+1)}s"); time.sleep(30*(attempt+1)); continue
                break
            if res is None:
                print(f"  {sym} {mo}: no data / error"); time.sleep(delay); continue
            if len(res):
                frames.append(res); got += len(res)
            time.sleep(delay)
        if frames:
            full = pd.concat(frames)
            full = full[~full.index.duplicated()].sort_index()
            full.to_parquet(path)
            print(f"{sym}: +{got} rows ({len(todo)} months) -> {len(full)} total  [{full.index.min()} .. {full.index.max()}]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="*")
    ap.add_argument("--universe", choices=["liquid100"], default=None)
    ap.add_argument("--start", default="2005-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--rpm", type=int, default=int(os.getenv("ALPHAVANTAGE_RPM", "5")))
    args = ap.parse_args()
    key = os.getenv("ALPHAVANTAGE_API_KEY")
    if not key:
        sys.exit("ALPHAVANTAGE_API_KEY missing — add it to .env (see the header of this file).")
    syms = args.symbols or (LIQUID100 if args.universe == "liquid100" else None)
    if not syms:
        sys.exit("give --symbols S1 S2 ... or --universe liquid100")
    print(f"symbols={len(syms)} start={args.start} rpm={args.rpm}")
    run(syms, args.start, args.end, args.rpm, key)


if __name__ == "__main__":
    main()
