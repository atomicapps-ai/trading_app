"""Shared helpers for pattern detectors — universal PQS modifiers,
time-scoping utilities, row accessors.

Universal modifiers (from pattern_recognition.md — applied after each
detector's pattern-specific modifiers):
    + volume_confirmation  : +10  (volume_ratio >= 1.5)
    + strong_volume        : +15  (volume_ratio >= 2.0, replaces the +10)
    + rsi_bullish_zone     : +8   (50 <= rsi_14 <= 70 on long setups)
    + rsi_strong           : +5   (rsi_14 > 60 on long)
    + ma_stack             : +8   (price > sma20 > sma50)
    + ma_trend             : +7   (price > sma200)
    + no_earnings_7d       : +5   (not within earnings blackout window)
    + vix_low              : +5   (vix < 25)
    + spy_trend            : +5   (SPY 20-day return aligned with signal direction)
    + sector_alignment     : +7   (sector ETF 20-day return aligned)

Earnings, VIX, SPY, and sector checks require ``macro_context`` which the
analyst passes in. Modifiers silently skip if the relevant context is
missing — detectors stay pure and the score just excludes that bonus.
"""
from __future__ import annotations

from typing import Any, Literal

import pandas as pd


# --------------------------------------------------------------------------- #
# Time scoping
# --------------------------------------------------------------------------- #


def slice_as_of(df: pd.DataFrame, as_of_ts: pd.Timestamp | None) -> pd.DataFrame:
    """Return ``df`` sliced to bars <= ``as_of_ts``. ``None`` = no-op.

    The slice is inclusive so an ``as_of_ts`` equal to the last bar's
    timestamp keeps that bar (the "current" snapshot). Any bar strictly
    after ``as_of_ts`` is a look-ahead leak and must be dropped.
    """
    if as_of_ts is None:
        return df
    if df.empty:
        return df
    return df.loc[:as_of_ts]


# --------------------------------------------------------------------------- #
# Row accessors
# --------------------------------------------------------------------------- #


def last_row(df: pd.DataFrame) -> pd.Series:
    return df.iloc[-1]


def safe(row: pd.Series, col: str, default: float = float("nan")) -> float:
    v = row.get(col, default)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# Universal PQS modifiers
# --------------------------------------------------------------------------- #


def apply_universal_modifiers(
    modifiers: dict[str, int],
    *,
    row: pd.Series,
    direction: Literal["long", "short"],
    macro_context: dict[str, Any] | None,
) -> None:
    """Mutates ``modifiers`` in place with universal bonus points.

    Returns nothing — callers add ``sum(modifiers.values()) + pqs_base``,
    cap at 100, and emit.
    """
    volume_ratio = safe(row, "volume_ratio")
    if not pd.isna(volume_ratio):
        if volume_ratio >= 2.0:
            modifiers["strong_volume"] = 15
        elif volume_ratio >= 1.5:
            modifiers["volume_confirmation"] = 10

    rsi = safe(row, "rsi_14")
    if not pd.isna(rsi):
        if direction == "long":
            if 50 <= rsi <= 70:
                modifiers["rsi_bullish_zone"] = 8
            if rsi > 60:
                modifiers["rsi_strong"] = 5
        else:
            if 30 <= rsi <= 50:
                modifiers["rsi_bearish_zone"] = 8
            if rsi < 40:
                modifiers["rsi_strong"] = 5

    close = safe(row, "close")
    sma20 = safe(row, "sma_20")
    sma50 = safe(row, "sma_50")
    sma200 = safe(row, "sma_200")
    if not (pd.isna(close) or pd.isna(sma20) or pd.isna(sma50)):
        if direction == "long" and close > sma20 > sma50:
            modifiers["ma_stack"] = 8
        elif direction == "short" and close < sma20 < sma50:
            modifiers["ma_stack"] = 8
    if not (pd.isna(close) or pd.isna(sma200)):
        if direction == "long" and close > sma200:
            modifiers["ma_trend"] = 7
        elif direction == "short" and close < sma200:
            modifiers["ma_trend"] = 7

    if macro_context:
        vix = macro_context.get("vix_level")
        if isinstance(vix, (int, float)) and vix < 25:
            modifiers["vix_low"] = 5

        spy_trend = macro_context.get("spy_trend_20d")
        if isinstance(spy_trend, (int, float)):
            if direction == "long" and spy_trend > 0:
                modifiers["spy_trend"] = 5
            elif direction == "short" and spy_trend < 0:
                modifiers["spy_trend"] = 5

        sector_rs = macro_context.get("sector_rs")
        if isinstance(sector_rs, (int, float)):
            if direction == "long" and sector_rs > 0:
                modifiers["sector_alignment"] = 7
            elif direction == "short" and sector_rs < 0:
                modifiers["sector_alignment"] = 7

        earnings_hours = macro_context.get("earnings_within_hours")
        if earnings_hours is None or (
            isinstance(earnings_hours, (int, float)) and earnings_hours > 7 * 24
        ):
            modifiers["no_earnings_7d"] = 5


def cap_pqs(pqs_base: int, modifiers: dict[str, int]) -> int:
    return min(100, pqs_base + sum(modifiers.values()))


# --------------------------------------------------------------------------- #
# Swing detection — shared by every pattern that compares two pivots
# --------------------------------------------------------------------------- #


def swing_low_indices(
    lows: pd.Series, left: int = 2, right: int = 2,
) -> list[int]:
    """Indices of swing lows in the series.

    A swing low at index i requires every value in (i-left..i) and
    (i..i+right) to be strictly higher than lows[i]. Ties are ignored
    on the strict-higher side so flat bottoms don't register as two
    pivots.
    """
    out: list[int] = []
    vals = lows.values
    n = len(vals)
    for i in range(left, n - right):
        v = vals[i]
        if all(vals[i - k] > v for k in range(1, left + 1)) and \
           all(vals[i + k] > v for k in range(1, right + 1)):
            out.append(i)
    return out


def swing_high_indices(
    highs: pd.Series, left: int = 2, right: int = 2,
) -> list[int]:
    """Mirror of ``swing_low_indices`` for swing highs."""
    out: list[int] = []
    vals = highs.values
    n = len(vals)
    for i in range(left, n - right):
        v = vals[i]
        if all(vals[i - k] < v for k in range(1, left + 1)) and \
           all(vals[i + k] < v for k in range(1, right + 1)):
            out.append(i)
    return out
