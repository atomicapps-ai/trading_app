"""supertrend_kivanc — Classic SuperTrend trend-flip strategy.

Pine source: strategies/external/supertrend_kivanc/source.pine
Author: KivancOzbilgic (TradingView)
Family: Trend-following (volatility-trailed band)

Algorithm:
  up = src - mult*ATR  (ratcheted: only moves up while close > prev up)
  dn = src + mult*ATR  (ratcheted: only moves down while close < prev dn)
  trend flips between +1 / -1 when close crosses the opposite band.

Entry: trend flip (+1->: long, -1->: short)
Stop: the band itself at entry (the price that would force a flip back)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from agents.detectors.external._base import Signal


META = {
    "slug": "supertrend_kivanc",
    "family": "trend_following",
    "natural_interval": "1d",  # works on intraday too; this is the primary
    "long_only": False,
    "source_url": None,
    "primitives": ["atr_trailed_band", "trend_flip", "ratcheted_stop"],
}


PARAMETER_SPEC = {
    "atr_period": {
        "default": 10, "type": int,
        "sweep": [7, 10, 14, 21],
        "reasoning": "ATR(14) is canonical; 10 is the SuperTrend default. "
                     "Shorter = more sensitive band ratchet.",
    },
    "atr_mult": {
        "default": 3.0, "type": float,
        "sweep": [1.5, 2.0, 2.5, 3.0, 4.0],
        "reasoning": "Dominant param. Lower = more flips/whipsaw; higher = "
                     "patient. Per-symbol optimum likely correlates with "
                     "the symbol's intrinsic volatility.",
    },
    "use_real_atr": {
        "default": True, "type": bool,
        "sweep": [True],   # changeATR=true is the author's recommended path
        "reasoning": "Author defaults to true (Wilder ATR). false = SMA of TR. "
                     "Holding fixed; not worth sweep slot.",
    },
}


def _atr(bars: pd.DataFrame, period: int, use_real: bool) -> pd.Series:
    high = bars["high"]
    low = bars["low"]
    close = bars["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    if use_real:
        # Wilder smoothing (RMA) — matches Pine's ta.atr()
        return tr.ewm(alpha=1.0 / period, adjust=False).mean()
    return tr.rolling(period).mean()


def detect(bars: pd.DataFrame, params: dict) -> list[Signal]:
    period = int(params.get("atr_period", 10))
    mult = float(params.get("atr_mult", 3.0))
    use_real = bool(params.get("use_real_atr", True))

    high = bars["high"].to_numpy()
    low = bars["low"].to_numpy()
    close = bars["close"].to_numpy()
    src = ((high + low) / 2.0)  # hl2

    atr = _atr(bars, period, use_real).to_numpy()
    n = len(bars)
    up = np.full(n, np.nan)
    dn = np.full(n, np.nan)
    trend = np.full(n, 1, dtype=int)

    # Iterative SuperTrend computation (matches Pine's recursive var)
    for i in range(n):
        if np.isnan(atr[i]):
            continue
        u = src[i] - mult * atr[i]
        d = src[i] + mult * atr[i]
        if i > 0 and not np.isnan(up[i - 1]):
            u = max(u, up[i - 1]) if close[i - 1] > up[i - 1] else u
            d = min(d, dn[i - 1]) if close[i - 1] < dn[i - 1] else d
        up[i] = u
        dn[i] = d
        if i == 0 or np.isnan(up[i - 1]):
            trend[i] = 1
        else:
            prev = trend[i - 1]
            if prev == -1 and close[i] > dn[i - 1]:
                trend[i] = 1
            elif prev == 1 and close[i] < up[i - 1]:
                trend[i] = -1
            else:
                trend[i] = prev

    signals: list[Signal] = []
    for i in range(1, n):
        if np.isnan(up[i]) or np.isnan(dn[i]):
            continue
        c = float(close[i])
        if trend[i] == 1 and trend[i - 1] == -1:
            stop = float(up[i])
            if stop < c:
                signals.append(Signal(
                    bar_idx=i, direction="long",
                    entry_price=c, stop_price=stop,
                    note=f"flip dn->up; atr={atr[i]:.3f}",
                ))
        elif trend[i] == -1 and trend[i - 1] == 1:
            stop = float(dn[i])
            if stop > c:
                signals.append(Signal(
                    bar_idx=i, direction="short",
                    entry_price=c, stop_price=stop,
                    note=f"flip up->dn; atr={atr[i]:.3f}",
                ))
    return signals
