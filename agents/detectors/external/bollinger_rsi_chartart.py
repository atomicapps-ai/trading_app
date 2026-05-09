"""bollinger_rsi_chartart — RSI + Bollinger Bands double-trigger mean reversion.

Pine source: strategies/external/bollinger_rsi_chartart/source.pine
Author: ChartArt (TradingView), v1.1, Jan 2015
Family: Mean reversion

Entry rule (long): RSI(N) crosses up through 50 AND close crosses up through
the lower BB on the same bar.
Entry rule (short): mirror — RSI crosses down through 50 AND close crosses
down through upper BB on same bar.

Stop: opposite BB at entry time (bar-relative). No TP — exit on opposite signal.

Notes on faithful translation:
- The Pine version uses `strategy.entry(stop=BBlower)` which Pine interprets
  as a stop-LIMIT entry ORDER (place order at BBlower, fill only if price
  reaches it). Implementing that exactly would mean most signals never fill
  (since the trigger requires close to have JUST crossed above BBlower).
- Our interpretation: market entry on signal-bar close (the cleaner mean-rev
  semantic), with a stop placed `stop_atr_mult * ATR` below entry for longs
  (or above for shorts). TP at the SMA basis (the textbook BB mean-rev target).
- This gives the strategy a fair shot in the optimizer rather than the
  near-zero-fill behavior of the literal translation.
"""
from __future__ import annotations

import pandas as pd

from agents.detectors.external._base import Signal


META = {
    "slug": "bollinger_rsi_chartart",
    "family": "mean_reversion",
    "natural_interval": "1d",
    "long_only": False,
    "source_url": None,
    "primitives": ["rsi", "bollinger_bands", "bar_relative_stop"],
}


PARAMETER_SPEC = {
    "rsi_length": {
        "default": 6, "type": int,
        "sweep": [4, 6, 8, 10, 14, 20],
        "reasoning": "Author default 6 is unusually fast (textbook RSI=14). "
                     "Sweep covers fast-mean-rev (4-8) and standard (14-20) regimes.",
    },
    "bb_length": {
        "default": 200, "type": int,
        "sweep": [20, 50, 100, 200],
        "reasoning": "Author default 200 = ~10 mo regime context on daily bars. "
                     "Shorter values turn it into a tactical mean-rev strategy.",
    },
    "bb_mult": {
        "default": 2.0, "type": float,
        "sweep": [1.5, 2.0, 2.5, 3.0],
        "reasoning": "Band width ↔ entry frequency trade-off. Higher mult = "
                     "rarer but stronger extreme touches.",
    },
    "stop_atr_mult": {
        "default": 1.5, "type": float,
        "sweep": [1.0, 1.5, 2.0, 3.0],
        "reasoning": "Distance from entry to stop, in ATR units. The Pine "
                     "version had no explicit protective stop; we add one "
                     "so the strategy is comparable to the others.",
    },
}


def _atr(bars: pd.DataFrame, period: int = 14) -> pd.Series:
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


def _rsi(close: pd.Series, length: int) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0)
    dn = -delta.clip(upper=0)
    # Wilder's smoothing (RMA) — matches Pine's ta.rsi() exactly
    roll_up = up.ewm(alpha=1.0 / length, adjust=False).mean()
    roll_dn = dn.ewm(alpha=1.0 / length, adjust=False).mean()
    rs = roll_up / roll_dn.replace(0, 1e-12)
    return 100.0 - 100.0 / (1.0 + rs)


def detect(bars: pd.DataFrame, params: dict) -> list[Signal]:
    rsi_len = int(params.get("rsi_length", 6))
    bb_len = int(params.get("bb_length", 200))
    bb_mult = float(params.get("bb_mult", 2.0))
    stop_atr_mult = float(params.get("stop_atr_mult", 1.5))

    close = bars["close"]
    rsi_v = _rsi(close, rsi_len)
    sma = close.rolling(bb_len).mean()
    std = close.rolling(bb_len).std()
    upper = sma + bb_mult * std
    lower = sma - bb_mult * std
    atr = _atr(bars, period=14)

    rsi_prev = rsi_v.shift(1)
    close_prev = close.shift(1)
    upper_prev = upper.shift(1)
    lower_prev = lower.shift(1)

    rsi_xover_50 = (rsi_v > 50) & (rsi_prev <= 50)
    rsi_xunder_50 = (rsi_v < 50) & (rsi_prev >= 50)
    close_xover_lower = (close > lower) & (close_prev <= lower_prev)
    close_xunder_upper = (close < upper) & (close_prev >= upper_prev)

    long_trigger = rsi_xover_50 & close_xover_lower
    short_trigger = rsi_xunder_50 & close_xunder_upper

    signals: list[Signal] = []
    for i in range(len(bars)):
        if not (long_trigger.iloc[i] or short_trigger.iloc[i]):
            continue
        if pd.isna(upper.iloc[i]) or pd.isna(lower.iloc[i]) or pd.isna(atr.iloc[i]):
            continue
        c = float(close.iloc[i])
        a = float(atr.iloc[i])
        if long_trigger.iloc[i]:
            stop = c - stop_atr_mult * a
            tp = float(sma.iloc[i])
            if stop < c < tp:
                signals.append(Signal(
                    bar_idx=i, direction="long",
                    entry_price=c, stop_price=stop, take_profit_price=tp,
                    note=f"rsi={rsi_v.iloc[i]:.1f}",
                ))
        else:
            stop = c + stop_atr_mult * a
            tp = float(sma.iloc[i])
            if stop > c > tp:
                signals.append(Signal(
                    bar_idx=i, direction="short",
                    entry_price=c, stop_price=stop, take_profit_price=tp,
                    note=f"rsi={rsi_v.iloc[i]:.1f}",
                ))
    return signals
