"""research_data — offline bar loader for the strategy lab.

Reads the cached CSVs in data/historical/{SYMBOL}_{interval}.csv (Date,Open,High,
Low,Close,Volume) into clean lowercase-column DataFrames with a tz-naive DatetimeIndex.
No network — so the backtest/iterate/document loop runs entirely on local files.

Intervals on disk: 1d, 1h, 30m, 15m. 4h is produced by resampling 1h.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# Kept import-light (no settings_service / app chain) so the strategy lab can run
# standalone. data/ lives at the project root, two levels up from this file.
HIST_DIR = Path(__file__).resolve().parent.parent / "data" / "historical"


def available(interval: str = "1d") -> list[str]:
    """Symbols that have a cached file for the given interval."""
    suffix = f"_{interval}.csv"
    return sorted(p.name[: -len(suffix)] for p in HIST_DIR.glob(f"*{suffix}"))


@lru_cache(maxsize=512)
def load(symbol: str, interval: str = "1d") -> pd.DataFrame:
    """Load one symbol/interval as OHLCV with a tz-naive DatetimeIndex (oldest-first)."""
    path = HIST_DIR / f"{symbol}_{interval}.csv"
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_csv(path)
    date_col = "Date" if "Date" in df.columns else df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col], utc=True, errors="coerce")
    df = df.dropna(subset=[date_col]).set_index(date_col).sort_index()
    df.index = df.index.tz_localize(None)
    df.columns = [c.lower() for c in df.columns]
    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    return df[keep].dropna()


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample OHLCV to a coarser bar (e.g. '4h', 'W-FRI', 'D')."""
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "volume" in df.columns:
        agg["volume"] = "sum"
    return df.resample(rule).agg(agg).dropna()


def load_multi(symbol: str):
    """Convenience: (weekly, daily, 4h) DataFrames for a symbol from cached files.

    Daily from the 1d file; weekly resampled from daily; 4h resampled from 1h
    (falls back to 30m if 1h is missing).
    """
    daily = load(symbol, "1d")
    weekly = resample(daily, "W-FRI")
    try:
        intraday = load(symbol, "1h")
        h4 = resample(intraday, "4h")
    except FileNotFoundError:
        h4 = pd.DataFrame()
    return weekly, daily, h4
