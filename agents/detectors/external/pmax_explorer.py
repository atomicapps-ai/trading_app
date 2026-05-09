"""pmax_explorer — ATR-trailed band on a moving average (a.k.a. PMax).

Pine source: strategies/external/pmax_explorer/source.pine
Author: KivancOzbilgic (TradingView)
Family: Trend-following (vol-trailed MA)

Algorithm:
  MAvg = MA(close, length, type)
  longStop = MAvg - mult*ATR  (ratcheted up while MAvg > prev longStop)
  shortStop = MAvg + mult*ATR (ratcheted down while MAvg < prev shortStop)
  PMax flips dir when MAvg crosses the opposite stop.

Entry: MAvg crosses PMax (== trend flip), same as SuperTrend logically but
with MA layer between price and the band (less whip on choppy bars).
Stop: PMax (band) at entry.

Translation: we follow the TOP of the Pine file (the inline computation),
not the inline `Pmax(M,P)` function which is only used by the multi-symbol
scanner. The multi-symbol scanner block (lines 146-325 of the Pine) is
purely presentational and is ignored.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from agents.detectors.external._base import Signal


META = {
    "slug": "pmax_explorer",
    "family": "trend_following",
    "natural_interval": "1d",
    "long_only": False,
    "source_url": None,
    "primitives": ["ma_smoothed_band", "atr_trailed", "ratcheted_stop"],
}


PARAMETER_SPEC = {
    "atr_period": {
        "default": 10, "type": int,
        "sweep": [7, 10, 14, 21],
        "reasoning": "Same role as SuperTrend's ATR period.",
    },
    "atr_mult": {
        "default": 3.0, "type": float,
        "sweep": [2.0, 2.5, 3.0, 4.0],
        "reasoning": "Band width; dominant param. Per-symbol vol-relative.",
    },
    "ma_length": {
        "default": 10, "type": int,
        "sweep": [8, 10, 14, 21],
        "reasoning": "MA smoothing on price. Longer = less whip, more lag.",
    },
    "ma_type": {
        "default": "EMA", "type": str,
        "sweep": ["EMA", "SMA", "WMA"],
        "reasoning": "Pine offers 8 MA types but EMA/SMA/WMA cover 95% of "
                     "real-world variants. Restrict to 3 to keep grid tractable.",
    },
}


def _ma(close: pd.Series, length: int, kind: str) -> pd.Series:
    if kind == "EMA":
        return close.ewm(span=length, adjust=False).mean()
    if kind == "SMA":
        return close.rolling(length).mean()
    if kind == "WMA":
        weights = np.arange(1, length + 1, dtype=float)
        return close.rolling(length).apply(
            lambda x: float(np.dot(x, weights) / weights.sum()), raw=True
        )
    raise ValueError(f"unsupported ma_type {kind!r}")


def _atr(bars: pd.DataFrame, period: int) -> pd.Series:
    high = bars["high"]
    low = bars["low"]
    close = bars["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def detect(bars: pd.DataFrame, params: dict) -> list[Signal]:
    period = int(params.get("atr_period", 10))
    mult = float(params.get("atr_mult", 3.0))
    ma_len = int(params.get("ma_length", 10))
    ma_type = str(params.get("ma_type", "EMA"))

    close = bars["close"]
    ma = _ma(close, ma_len, ma_type).to_numpy()
    atr = _atr(bars, period).to_numpy()

    n = len(bars)
    long_stop = np.full(n, np.nan)
    short_stop = np.full(n, np.nan)
    direction = np.zeros(n, dtype=int)

    for i in range(n):
        if np.isnan(atr[i]) or np.isnan(ma[i]):
            continue
        ls = ma[i] - mult * atr[i]
        ss = ma[i] + mult * atr[i]
        if i > 0 and not np.isnan(long_stop[i - 1]):
            ls = max(ls, long_stop[i - 1]) if ma[i] > long_stop[i - 1] else ls
            ss = min(ss, short_stop[i - 1]) if ma[i] < short_stop[i - 1] else ss
        long_stop[i] = ls
        short_stop[i] = ss
        if i == 0 or direction[i - 1] == 0:
            direction[i] = 1
        else:
            prev = direction[i - 1]
            if prev == -1 and ma[i] > short_stop[i - 1]:
                direction[i] = 1
            elif prev == 1 and ma[i] < long_stop[i - 1]:
                direction[i] = -1
            else:
                direction[i] = prev

    signals: list[Signal] = []
    for i in range(1, n):
        if np.isnan(long_stop[i]) or np.isnan(short_stop[i]):
            continue
        c = float(close.iloc[i])
        if direction[i] == 1 and direction[i - 1] == -1:
            stop = float(long_stop[i])
            if stop < c:
                signals.append(Signal(
                    bar_idx=i, direction="long",
                    entry_price=c, stop_price=stop,
                    note=f"ma->long; atr={atr[i]:.3f}",
                ))
        elif direction[i] == -1 and direction[i - 1] == 1:
            stop = float(short_stop[i])
            if stop > c:
                signals.append(Signal(
                    bar_idx=i, direction="short",
                    entry_price=c, stop_price=stop,
                    note=f"ma->short; atr={atr[i]:.3f}",
                ))
    return signals
