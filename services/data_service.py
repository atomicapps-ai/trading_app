"""data_service.py — OHLCV bar cache layer.

All agents and lenses read bars through here. Never import yfinance
outside this file. The `as_of_ts` parameter is the cornerstone of
Phase 5 backtesting — given a historical timestamp, the returned
frame is sliced to `df.loc[:as_of_ts]` so no future bars leak in.

Cache layout:
    data/historical/{SYMBOL}_{interval}.csv
    intervals: "1d" (daily), "1h" (hourly), "30m" (intraday — 60-day cap)

The 30-min interval was added for the intraday Double Lock detector
(``agents/detectors/double_lock_filtered.py``). yfinance only returns
the last ~60 days of 30-min bars, so this interval's cache turns over
quickly — pre-market refresh is essential for live use.

CSV format (new downloads, auto_adjust=True):
    Date (index, tz-aware), Open, High, Low, Close, Volume

Back-compat: older CSVs written by scripts/download_history.py used
auto_adjust=False and have an "Adj Close" column. We honor that:
the adjusted close is promoted to the canonical `close` column and
the raw `Close` is dropped. Open/High/Low stay as written — the
small unadjusted-OHL vs adjusted-C skew is acceptable for swing
pattern detection on modern data (and we re-download on refresh).

All I/O is wrapped with asyncio.to_thread so FastAPI routes can
await without blocking the event loop.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Literal

import pandas as pd
import yfinance as yf

from services.settings_service import DATA_DIR

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Paths + constants
# --------------------------------------------------------------------------- #

HISTORICAL_DIR: Path = DATA_DIR / "historical"

Interval = Literal["1d", "1h", "30m"]

# yfinance download windows per interval. Hourly data from Yahoo is
# only reliably available for the last ~730 days. 30-min bars cap at
# ~60 days (so we always request 60d and let Yahoo trim).
_DEFAULT_PERIOD: dict[Interval, str] = {
    "1d": "20y",
    "1h": "2y",
    "30m": "60d",
}

# Minimum bars the caller must actually receive before we call the
# result usable. Pattern detectors can require more (cup-and-handle
# wants ≥200 daily) — they should validate that themselves.
DEFAULT_MIN_BARS = 50

# Canonical column set returned to callers. Everything else is dropped.
_CANONICAL_COLS = ("open", "high", "low", "close", "volume")


# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class DataNotAvailableError(Exception):
    """Raised when bars are not cached and (a) download is disabled or
    (b) download succeeded but produced fewer than `min_bars` rows within
    the requested `as_of_ts` window."""


# --------------------------------------------------------------------------- #
# Internal helpers (sync — wrapped via to_thread by the public API)
# --------------------------------------------------------------------------- #


def _cache_path(symbol: str, interval: Interval) -> Path:
    return HISTORICAL_DIR / f"{symbol.upper()}_{interval}.csv"


def _download_sync(symbol: str, interval: Interval) -> pd.DataFrame:
    """Hit yfinance, write the CSV, return the normalized frame.

    Uses auto_adjust=True so Close/Open/High/Low are all split+dividend
    adjusted. Raises DataNotAvailableError on empty result.
    """
    period = _DEFAULT_PERIOD[interval]
    log.info("yfinance download: %s %s period=%s", symbol, interval, period)
    try:
        df = yf.Ticker(symbol).history(
            period=period,
            interval=interval,
            auto_adjust=True,
        )
    except Exception as e:  # yfinance raises a grab-bag
        raise DataNotAvailableError(
            f"yfinance download failed for {symbol} {interval}: "
            f"{type(e).__name__}: {e}"
        ) from e

    if df.empty:
        raise DataNotAvailableError(
            f"yfinance returned empty frame for {symbol} {interval} "
            f"(bad ticker, or Yahoo has no data?)"
        )

    HISTORICAL_DIR.mkdir(parents=True, exist_ok=True)
    out = _cache_path(symbol, interval)
    df.to_csv(out)
    log.info("cached %d rows → %s", len(df), out.name)
    return _normalize(df)


def _read_sync(symbol: str, interval: Interval) -> pd.DataFrame | None:
    """Read a cached CSV and normalize it. Returns None if the file is missing."""
    path = _cache_path(symbol, interval)
    if not path.exists():
        return None
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    return _normalize(df)


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase columns, UTC index, ascending sort, canonical columns only."""
    df = df.copy()

    # --- Columns ----------------------------------------------------------
    # Lowercase everything; handle "Adj Close" → adj_close (with space).
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

    # Back-compat: old CSVs (auto_adjust=False) carry both `close` and
    # `adj_close`. The adjusted series is what belongs on charts, so
    # promote it and drop the raw close. New CSVs (auto_adjust=True)
    # have no adj_close column — already canonical.
    if "adj_close" in df.columns and "close" in df.columns:
        df["close"] = df["adj_close"]
    df = df.drop(
        columns=[c for c in df.columns if c not in _CANONICAL_COLS],
        errors="ignore",
    )

    # --- Index ------------------------------------------------------------
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")

    df = df.sort_index(ascending=True)

    # --- Sanity pass ------------------------------------------------------
    # Drop fully-NaN rows that yfinance occasionally emits for half-days.
    df = df.dropna(how="all")

    missing = [c for c in _CANONICAL_COLS if c not in df.columns]
    if missing:
        raise DataNotAvailableError(
            f"normalized frame missing required columns: {missing}"
        )

    return df[list(_CANONICAL_COLS)]


def _slice_as_of(df: pd.DataFrame, as_of_ts: pd.Timestamp | None) -> pd.DataFrame:
    """Apply the backtest-safety slice `df.loc[:as_of_ts]`. Coerces tz if needed."""
    if as_of_ts is None:
        return df
    ts = pd.Timestamp(as_of_ts)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return df.loc[:ts]


# --------------------------------------------------------------------------- #
# Public async API
# --------------------------------------------------------------------------- #


async def get_bars(
    symbol: str,
    interval: Interval,
    as_of_ts: pd.Timestamp | None = None,
    min_bars: int = DEFAULT_MIN_BARS,
    download_if_missing: bool = True,
) -> pd.DataFrame:
    """Return OHLCV DataFrame for `symbol` at `interval`.

    Columns (lowercase): open, high, low, close, volume.
    Index: DatetimeIndex, UTC-aware, ascending (oldest first).

    `as_of_ts` — the "now" the caller is simulating. When given, the
    returned frame is sliced to `df.loc[:as_of_ts]`. Live callers pass
    None; Phase 5 backtests pass the historical timestamp under test.

    `min_bars` — if the post-slice frame has fewer rows, we raise
    DataNotAvailableError. Lets callers opt into fail-fast behavior
    rather than silently pattern-matching on 3 bars.

    `download_if_missing` — on cache miss, try yfinance once. If the
    cache is present but stale relative to `as_of_ts`, we still return
    what we have (Phase 5 bar-cache refresh is a separate concern).
    """
    symbol = symbol.upper()

    df = await asyncio.to_thread(_read_sync, symbol, interval)
    if df is None:
        if not download_if_missing:
            raise DataNotAvailableError(
                f"no cached bars for {symbol} {interval} and "
                f"download_if_missing=False"
            )
        df = await asyncio.to_thread(_download_sync, symbol, interval)

    sliced = _slice_as_of(df, as_of_ts)
    if len(sliced) < min_bars:
        raise DataNotAvailableError(
            f"{symbol} {interval}: only {len(sliced)} bars <= {as_of_ts}, "
            f"need {min_bars}"
        )
    return sliced


async def refresh_bars(symbol: str, interval: Interval) -> pd.DataFrame:
    """Force re-download from yfinance, rewrite the CSV, return the frame.

    Ignores any existing cache. Use when you suspect the cache is
    stale (e.g. the pre-market refresh job before morning_run).
    """
    symbol = symbol.upper()
    return await asyncio.to_thread(_download_sync, symbol, interval)


async def get_bars_multi(
    symbols: list[str],
    interval: Interval,
    as_of_ts: pd.Timestamp | None = None,
    min_bars: int = DEFAULT_MIN_BARS,
    download_if_missing: bool = True,
) -> dict[str, pd.DataFrame]:
    """Batch fetch bars for many symbols.

    Returns dict of symbol → DataFrame. Per-symbol errors are logged
    and that symbol is omitted from the result — we never raise, so
    one bad ticker doesn't kill an entire pipeline run.

    Fetches run in parallel via asyncio.gather. yfinance is a blocking
    sync API so each fetch runs in its own thread (to_thread); the
    concurrency ceiling in practice is the thread pool default (~32).
    """
    async def _one(sym: str) -> tuple[str, pd.DataFrame | None]:
        try:
            df = await get_bars(
                sym,
                interval,
                as_of_ts=as_of_ts,
                min_bars=min_bars,
                download_if_missing=download_if_missing,
            )
            return sym.upper(), df
        except DataNotAvailableError as e:
            log.warning("get_bars_multi: skipping %s — %s", sym, e)
            return sym.upper(), None
        except Exception as e:  # defensive — never kill the batch
            log.exception("get_bars_multi: unexpected error for %s: %s", sym, e)
            return sym.upper(), None

    pairs = await asyncio.gather(*(_one(s) for s in symbols))
    return {sym: df for sym, df in pairs if df is not None}


async def ensure_cached(
    symbol: str,
    interval: Interval,
) -> Path:
    """Ensure the symbol is in the cache; download if missing.

    Convenience for scripts that want to pre-populate data/historical/
    without caring about the DataFrame itself. Returns the CSV path.
    """
    symbol = symbol.upper()
    path = _cache_path(symbol, interval)
    if path.exists():
        return path
    await asyncio.to_thread(_download_sync, symbol, interval)
    return path
