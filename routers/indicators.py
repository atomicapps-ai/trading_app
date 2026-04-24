"""indicators router — technical indicator series for chart overlays.

One endpoint: ``GET /api/indicators/{symbol}?interval=&indicators=&limit=``.

This is the **single source of truth** for indicator math used by chart
overlays. The agents already compute their indicators through
``services/indicator_service.py``; this router wraps the same module so
the chart UI and the trading agents always see identical numbers.

Supported indicator IDs (comma-separated in the ``indicators`` query):

    sma20, sma50, sma200          — simple moving averages
    ema20                         — exponential MA
    bb                            — Bollinger Bands (upper/middle/lower, 20/2σ)
    vwap                          — session-reset VWAP
    rsi                           — RSI(14)
    atr                           — ATR(14)
    macd                          — MACD(12,26,9) — line/signal/hist
    volume                        — Volume + 20-bar SMA reference
    hl20, hl50, hl52w             — rolling high/low bands
                                    (52w = 252 daily bars; on intraday
                                    intervals these collapse to the
                                    longest sensible window)

Response shape — matched to what Lightweight Charts ingests directly:

    {
      "symbol": "AAPL",
      "interval": "1h",
      "count": 500,
      "indicators": {
        "sma20":      [{"time": 1709251200, "value": 182.45}, ...],
        "bb_upper":   [...], "bb_middle": [...], "bb_lower": [...],
        "macd_line":  [...], "macd_signal": [...],
        "macd_hist":  [{"time": ..., "value": ..., "color": "#1db87a"}, ...],
        "volume":     [{"time": ..., "value": ..., "color": "..."}, ...],
        ...
      }
    }

Notes
-----
* NaN values (warm-up bars before the indicator stabilises) are dropped
  from each series — Lightweight Charts cannot render NaN points.
* For ``volume`` and ``macd_hist`` we attach a per-bar color so the chart
  can render them as a green/red histogram without re-doing the math
  client-side.
* The 2h/4h intervals are resampled from the cached 1h series, identical
  to ``routers/bars.py`` — keeps the indicator math consistent with what
  the chart's candle data shows.
"""
from __future__ import annotations

import logging
from typing import Literal

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from services.data_service import DataNotAvailableError, get_bars
from services.indicator_service import add_indicators

logger = logging.getLogger(__name__)
router = APIRouter()

SupportedInterval = Literal["1h", "2h", "4h", "1d"]
_RESAMPLE_RULE = {"1h": "1h", "2h": "2h", "4h": "4h", "1d": "1D"}

# All indicator IDs the endpoint will recognize. Anything else in the
# query is silently ignored — keeps the contract forgiving.
_KNOWN_INDICATORS = {
    "sma20", "sma50", "sma200", "ema20",
    "bb", "vwap",
    "rsi", "atr", "macd", "volume",
    "hl20", "hl50", "hl52w",
}

# Hex colors used for the bullish / bearish bars on volume + MACD
# histogram. Match the candle colors used in the chart panels so the
# volume/MACD bar tint always lines up with the candle tint.
_UP_COLOR = "#1db87a"
_DOWN_COLOR = "#e05252"


def _series(df: pd.DataFrame, col: str) -> list[dict]:
    """Convert a DataFrame column into the [{time, value}] shape that
    Lightweight Charts' line/area series consume. Drops NaN warm-up bars."""
    if col not in df.columns:
        return []
    s = df[col].dropna()
    return [
        {"time": int(ts.timestamp()), "value": float(v)}
        for ts, v in s.items()
    ]


def _colored_series(
    df: pd.DataFrame, value_col: str, color_col_or_func
) -> list[dict]:
    """Same as ``_series`` but each point gets a per-bar color attached.

    ``color_col_or_func`` can be either a column name (looked up in df)
    or a callable that takes a row and returns a hex string.
    """
    if value_col not in df.columns:
        return []
    s = df[value_col].dropna()
    out: list[dict] = []
    for ts, v in s.items():
        if callable(color_col_or_func):
            color = color_col_or_func(df.loc[ts])
        else:
            color = str(df.loc[ts, color_col_or_func])
        out.append({
            "time": int(ts.timestamp()),
            "value": float(v),
            "color": color,
        })
    return out


def _highlow_window(interval: str, days: int) -> int:
    """Translate a 'days' lookback into a bar count for the requested
    interval. The 52w/50d/20d windows are conventionally expressed in
    trading days; on intraday intervals we expand the bar count to keep
    the same wall-clock window.

    Approx bars-per-day per interval:
        1d → 1
        4h → ~2
        2h → ~3
        1h → ~7  (regular session 9:30–16:00 → 6.5 hr)
    """
    bars_per_day = {"1d": 1, "4h": 2, "2h": 3, "1h": 7}.get(interval, 1)
    return max(2, int(days * bars_per_day))


@router.get("/api/indicators/{symbol}")
async def get_indicators_json(
    symbol: str,
    interval: str = Query("1h"),
    indicators: str = Query(
        "",
        description="Comma-separated indicator IDs. Empty = no indicators "
                    "computed (fast no-op). See module docstring for the "
                    "full list of supported IDs.",
    ),
    limit: int = Query(500, ge=10, le=5000),
    before: int | None = Query(
        None,
        description="UNIX epoch seconds. Returns indicator values aligned "
                    "with bars strictly before this timestamp. Mirrors the "
                    "bars-router pagination so the chart's overlay stays "
                    "aligned with its candle data.",
    ),
) -> dict:
    if interval not in _RESAMPLE_RULE:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported interval {interval!r}; expected one of "
                   f"{list(_RESAMPLE_RULE.keys())}",
        )

    requested = {x.strip().lower() for x in indicators.split(",") if x.strip()}
    requested &= _KNOWN_INDICATORS  # ignore unknowns silently

    source_interval = "1d" if interval == "1d" else "1h"
    try:
        df = await get_bars(symbol.upper(), source_interval, min_bars=50)
    except DataNotAvailableError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if interval in ("2h", "4h"):
        df = _resample(df, _RESAMPLE_RULE[interval])

    if before is not None:
        cutoff = pd.Timestamp(before, unit="s", tz="UTC")
        df = df.loc[df.index < cutoff]

    # Compute the full indicator set against the trailing window. We use
    # `limit + 250` extra bars to give RSI/SMA(200) a clean warm-up;
    # the response only ever returns the trailing `limit` rows.
    warmup = 250
    df_full = df.tail(limit + warmup)
    if df_full.empty or len(df_full) < 2:
        return {
            "symbol": symbol.upper(),
            "interval": interval,
            "count": 0,
            "indicators": {},
        }

    enriched = add_indicators(df_full)

    # Extra rolling-window indicators not in add_indicators' standard set:
    # the High/Low bands. Computed only when requested.
    if "hl20" in requested:
        w = _highlow_window(interval, 20)
        enriched["hl20_high"] = enriched["high"].rolling(w, min_periods=w).max()
        enriched["hl20_low"] = enriched["low"].rolling(w, min_periods=w).min()
    if "hl50" in requested:
        w = _highlow_window(interval, 50)
        enriched["hl50_high"] = enriched["high"].rolling(w, min_periods=w).max()
        enriched["hl50_low"] = enriched["low"].rolling(w, min_periods=w).min()
    if "hl52w" in requested:
        w = _highlow_window(interval, 252)
        enriched["hl52w_high"] = enriched["high"].rolling(w, min_periods=w).max()
        enriched["hl52w_low"] = enriched["low"].rolling(w, min_periods=w).min()

    # Trim back to the requested window so the response aligns with what
    # /api/bars would return for the same symbol/interval/limit/before.
    enriched = enriched.tail(limit)

    out: dict[str, list[dict]] = {}

    if "sma20" in requested:
        out["sma20"] = _series(enriched, "sma_20")
    if "sma50" in requested:
        out["sma50"] = _series(enriched, "sma_50")
    if "sma200" in requested:
        out["sma200"] = _series(enriched, "sma_200")
    if "ema20" in requested:
        out["ema20"] = _series(enriched, "ema_20")

    if "bb" in requested:
        out["bb_upper"] = _series(enriched, "bb_upper_20")
        out["bb_middle"] = _series(enriched, "bb_middle_20")
        out["bb_lower"] = _series(enriched, "bb_lower_20")

    if "vwap" in requested:
        out["vwap"] = _series(enriched, "vwap")

    if "rsi" in requested:
        out["rsi"] = _series(enriched, "rsi_14")

    if "atr" in requested:
        out["atr"] = _series(enriched, "atr_14")

    if "macd" in requested:
        out["macd_line"] = _series(enriched, "macd_line")
        out["macd_signal"] = _series(enriched, "macd_signal")
        # Histogram colors: positive=green, negative=red.
        def _macd_color(row):
            return _UP_COLOR if row["macd_hist"] >= 0 else _DOWN_COLOR
        out["macd_hist"] = _colored_series(enriched, "macd_hist", _macd_color)

    if "volume" in requested:
        # Color by candle direction: close >= open → green, else red.
        def _vol_color(row):
            return _UP_COLOR if row["close"] >= row["open"] else _DOWN_COLOR
        out["volume"] = _colored_series(enriched, "volume", _vol_color)
        out["volume_sma"] = _series(enriched, "volume_sma_20")

    if "hl20" in requested:
        out["hl20_high"] = _series(enriched, "hl20_high")
        out["hl20_low"] = _series(enriched, "hl20_low")
    if "hl50" in requested:
        out["hl50_high"] = _series(enriched, "hl50_high")
        out["hl50_low"] = _series(enriched, "hl50_low")
    if "hl52w" in requested:
        out["hl52w_high"] = _series(enriched, "hl52w_high")
        out["hl52w_low"] = _series(enriched, "hl52w_low")

    return {
        "symbol": symbol.upper(),
        "interval": interval,
        "count": len(enriched),
        "indicators": out,
    }


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Pandas OHLCV resample. Drops empty intervals.

    Mirrors routers/bars.py — keep them in lockstep so the indicators
    line up bar-for-bar with the candles on the chart.
    """
    resampled = df.resample(rule, label="right", closed="right").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()
    return resampled
