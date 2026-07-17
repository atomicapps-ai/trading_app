"""bars router — OHLCV data for the chart widget on /pending.

One endpoint: ``GET /api/bars/{symbol}?interval=<1h|2h|4h|1d>&limit=N``.

Resampling
----------
``data_service`` caches native intervals ``1d``, ``1h``, ``30m``,
``15m`` and ``5m`` (the sub-hourly ones from yfinance, ~60-day cap).
Everything else is resampled here so we don't store extra CSVs:

    ``2h`` / ``4h``  ← resampled from the ``1h`` cache
    ``10m``          ← resampled from the ``5m`` cache
    ``1w`` / ``1mo`` ← resampled from the ``1d`` cache (20y deep, so
                       weekly/monthly get full history with no new download)

``1d`` / ``1h`` / ``30m`` / ``15m`` / ``5m`` are served directly.

Response shape matches what ``lightweight-charts`` expects:

    [
        { "time": 1709251200, "open": 100.0, "high": 101.5,
          "low": 99.8, "close": 100.7, "volume": 1234567 },
        ...
    ]

``time`` is a UNIX epoch second (UTC). Lightweight Charts will plot
these as UTC bars — which for daily equities charts is what you want
(each day's session shows up as one candle regardless of viewer TZ).
"""
from __future__ import annotations

import logging
from typing import Literal

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from services.data_service import DataNotAvailableError, get_bars

logger = logging.getLogger(__name__)
router = APIRouter()

SupportedInterval = Literal[
    "5m", "10m", "15m", "30m", "1h", "2h", "4h", "1d", "1w", "1mo",
]
_RESAMPLE_RULE = {
    "5m": "5min", "10m": "10min", "15m": "15min", "30m": "30min",
    "1h": "1h", "2h": "2h", "4h": "4h", "1d": "1D",
    # Weekly bars end Friday (equity trading week); monthly = calendar
    # month-end. pandas 3.0 requires "ME" (not the old "M").
    "1w": "W-FRI", "1mo": "ME",
}
# Intervals we resample on the fly (target → source cache to pull).
_RESAMPLE_FROM = {"2h": "1h", "4h": "1h", "10m": "5m", "1w": "1d", "1mo": "1d"}


@router.get("/api/bars/{symbol}")
async def get_bars_json(
    symbol: str,
    interval: str = Query("1h"),
    limit: int = Query(500, ge=10, le=5000),
    before: int | None = Query(
        None, description="UNIX epoch seconds. Return <=limit bars ending "
                          "strictly before this timestamp. Used for "
                          "scroll-back lazy loading on the chart widget.",
    ),
) -> dict:
    if interval not in _RESAMPLE_RULE:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported interval {interval!r}; expected one of "
                   f"{list(_RESAMPLE_RULE.keys())}",
        )

    # Pick source cache: native intervals map to themselves; resampled
    # intervals (2h/4h from 1h, 10m from 5m) pull their source cache.
    source_interval = _RESAMPLE_FROM.get(interval, interval)

    try:
        df = await get_bars(symbol.upper(), source_interval, min_bars=20)
    except DataNotAvailableError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if interval in _RESAMPLE_FROM:
        df = _resample(df, _RESAMPLE_RULE[interval])

    # If the client is paginating backwards, slice to bars strictly before
    # the provided epoch BEFORE taking the tail. That way each page fills
    # ``limit`` bars ending just before the client's current oldest bar.
    if before is not None:
        cutoff = pd.Timestamp(before, unit="s", tz="UTC")
        df = df.loc[df.index < cutoff]

    df = df.tail(limit)

    out = []
    for ts, row in df.iterrows():
        o, h, l, c = row["open"], row["high"], row["low"], row["close"]
        # Skip rows with a NaN in any OHLC field: pandas gaps / partial live
        # bars produce NaN, which would either 500 the JSON encode (allow_nan
        # is off) or reach the chart as a null and throw "Value is null".
        if pd.isna(o) or pd.isna(h) or pd.isna(l) or pd.isna(c):
            continue
        vol = row["volume"]
        out.append({
            "time": int(ts.timestamp()),
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
            "volume": 0.0 if pd.isna(vol) else float(vol),
        })
    return {
        "symbol": symbol.upper(),
        "interval": interval,
        "count": len(out),
        # When the server returned fewer bars than requested AND ``before``
        # was set, the client knows it's reached the start of available data.
        "has_more": (before is not None) and len(out) >= limit,
        "bars": out,
    }


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Pandas OHLCV resample. Drops empty intervals."""
    resampled = df.resample(rule, label="right", closed="right").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()
    return resampled
