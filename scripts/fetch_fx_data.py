"""fetch_fx_data — download free 1-minute FX history from HistData.com, resample to
5m/15m/30m/1h (+1d), and save to data/historical/{PAIR}_{interval}.csv in the SAME
format data_service / the backtest harness already read (so FX symbols load identically
to stocks). Unlocks the shelved intraday-FX strategies.

INSTALL (on your machine — the package does the authenticated download dance):
    pip install histdata

RUN:
    python scripts/fetch_fx_data.py                       # default pairs, 2015->now
    python scripts/fetch_fx_data.py --pairs eurusd usdjpy --start-year 2018
    python scripts/fetch_fx_data.py --intervals 5m 15m 30m 1h 1d

NOTES:
  * HistData M1 timestamps are EST (UTC-5, NO daylight saving). We localize to UTC-5
    and store UTC tz-aware timestamps — unambiguous, and session logic (London/NY/Asia)
    converts cleanly later.
  * FX has no real volume; HistData volume is 0. We keep a Volume column (0) so the
    schema matches the stock CSVs; volume-based filters simply won't fire on FX.
  * Skips (pair, year) files already present locally so re-runs are incremental.
"""
from __future__ import annotations
import argparse
import io
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
HIST = ROOT / "data" / "historical"
RAW = ROOT / "data" / "fx_raw"          # cached HistData zips/csvs
HIST.mkdir(parents=True, exist_ok=True)
RAW.mkdir(parents=True, exist_ok=True)

# Pairs the shelved strategies need (majors + the specific crosses called out in notes).
DEFAULT_PAIRS = ["eurusd", "usdjpy", "eurjpy", "gbpjpy", "audjpy",
                 "euraud", "eurcad", "gbpusd", "audusd"]

# app interval suffix -> pandas resample rule
INTERVAL_RULE = {"5m": "5min", "15m": "15min", "30m": "30min", "1h": "60min", "1d": "1D"}


# --------------------------------------------------------------------------- #
# Parsing + resampling (pure, unit-testable without any network)
# --------------------------------------------------------------------------- #
def parse_histdata_m1(text: str) -> pd.DataFrame:
    """Parse HistData GENERIC_ASCII M1 text. Each line:
        YYYYMMDD HHMMSS;OPEN;HIGH;LOW;CLOSE;VOLUME
    Returns a UTC-indexed OHLCV frame (timestamps are EST/UTC-5, no DST)."""
    df = pd.read_csv(
        io.StringIO(text), sep=";", header=None,
        names=["ts", "open", "high", "low", "close", "volume"],
        dtype={"ts": str},
    )
    if df.empty:
        return df
    naive = pd.to_datetime(df["ts"], format="%Y%m%d %H%M%S", errors="coerce")
    # HistData is EST = UTC-5 with NO daylight saving -> Etc/GMT+5 is exactly UTC-5
    idx = naive.dt.tz_localize("Etc/GMT+5").dt.tz_convert("UTC")
    out = df[["open", "high", "low", "close", "volume"]].copy()
    out.index = idx
    return out.dropna().sort_index()


def resample_ohlc(df1m: pd.DataFrame, rule: str) -> pd.DataFrame:
    if df1m.empty:
        return df1m
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    r = df1m.resample(rule, label="left", closed="left").agg(agg).dropna(subset=["open"])
    return r


def save_like_data_service(df: pd.DataFrame, sym: str, interval: str, out_dir: Path = HIST) -> Path:
    """Write {out_dir}/{SYM}_{interval}.csv matching the stock CSV schema:
    first col Date/Datetime, then Open,High,Low,Close,Volume,Dividends,Stock Splits."""
    first_col = "Date" if interval == "1d" else "Datetime"
    out = df.copy()
    out.columns = ["Open", "High", "Low", "Close", "Volume"]
    out["Dividends"] = 0.0
    out["Stock Splits"] = 0.0
    out.index.name = first_col
    path = out_dir / f"{sym.upper()}_{interval}.csv"
    out.to_csv(path)
    return path


# --------------------------------------------------------------------------- #
# Download (uses the histdata package; cached to data/fx_raw)
# --------------------------------------------------------------------------- #
def _read_year_m1(pair: str, year: int) -> pd.DataFrame:
    """Download (or load cached) one (pair, year) M1 file -> parsed frame."""
    try:
        from histdata import download_hist_data
        from histdata.api import Platform, TimeFrame
    except ImportError:
        sys.exit("Missing dependency: pip install histdata")

    frames: list[pd.DataFrame] = []
    now = datetime.now(timezone.utc)
    months = [None] if year < now.year else list(range(1, now.month + 1))
    for mo in months:
        tag = f"{pair}_{year}" + (f"_{mo:02d}" if mo else "")
        cached = RAW / f"DAT_ASCII_{pair.upper()}_M1_{year}{(f'{mo:02d}' if mo else '')}.csv"
        if not cached.exists():
            try:
                zip_path = download_hist_data(year=str(year), month=(str(mo) if mo else None),
                                              pair=pair, platform=Platform.GENERIC_ASCII,
                                              time_frame=TimeFrame.ONE_MINUTE,
                                              output_directory=str(RAW))
            except Exception as e:  # noqa: BLE001
                print(f"  ! {tag}: download failed ({e})")
                continue
            try:
                with zipfile.ZipFile(zip_path) as z:
                    name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
                    cached.write_bytes(z.read(name))
                Path(zip_path).unlink(missing_ok=True)
            except Exception as e:  # noqa: BLE001
                print(f"  ! {tag}: unzip failed ({e})")
                continue
        frames.append(parse_histdata_m1(cached.read_text(encoding="utf-8", errors="ignore")))
    return pd.concat(frames).sort_index() if frames else pd.DataFrame()


def fetch_pair(pair: str, start_year: int, intervals: list[str]) -> None:
    now_year = datetime.now(timezone.utc).year
    parts = []
    for y in range(start_year, now_year + 1):
        m1 = _read_year_m1(pair, y)
        if not m1.empty:
            parts.append(m1)
            print(f"  {pair} {y}: {len(m1):,} 1m bars")
    if not parts:
        print(f"  {pair}: no data fetched"); return
    m1 = pd.concat(parts).sort_index()
    m1 = m1[~m1.index.duplicated(keep="last")]
    for iv in intervals:
        rule = INTERVAL_RULE[iv]
        out = save_like_data_service(resample_ohlc(m1, rule), pair, iv)
        print(f"    saved {out.name} ({iv})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", nargs="+", default=DEFAULT_PAIRS)
    ap.add_argument("--start-year", type=int, default=2015)
    ap.add_argument("--intervals", nargs="+", default=["5m", "15m", "30m", "1h", "1d"])
    ap.add_argument("--selftest", action="store_true", help="run parse/resample unit test only")
    args = ap.parse_args()

    if args.selftest:
        _selftest(); return

    bad = [iv for iv in args.intervals if iv not in INTERVAL_RULE]
    if bad:
        sys.exit(f"unknown intervals {bad}; choose from {list(INTERVAL_RULE)}")
    for p in args.pairs:
        print(f"=== {p} ===")
        fetch_pair(p, args.start_year, args.intervals)
    print("done. FX symbols now load identically to stocks in data/historical/.")


def _selftest() -> None:
    sample = "\n".join(
        f"20240102 17{m:02d}00;1.1000{m%10};1.1002{m%10};1.0999{m%10};1.1001{m%10};0"
        for m in range(0, 12)
    )
    df = parse_histdata_m1(sample)
    assert str(df.index.tz) == "UTC" and len(df) == 12, "parse failed"
    # 17:00 EST == 22:00 UTC; 5-min bars -> first bar covers 22:00-22:05 = 5 minutes
    r5 = resample_ohlc(df, "5min")
    assert r5["open"].iloc[0] == df["open"].iloc[0], "resample open mismatch"
    assert r5["high"].iloc[0] == df["high"].iloc[:5].max(), "resample high mismatch"
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    saved = save_like_data_service(r5, "TESTFX", "5m", out_dir=tmp)
    back = pd.read_csv(saved)
    assert list(back.columns) == ["Datetime", "Open", "High", "Low", "Close", "Volume", "Dividends", "Stock Splits"]
    saved.unlink(missing_ok=True)
    print(f"selftest OK — parsed {len(df)} 1m bars, {len(r5)} 5m bars, schema matches data_service")


if __name__ == "__main__":
    main()
