"""lock1_scout.py — DL early-warning detector at 10:00 ET.

After the first 30-min candle closes, evaluate the same conviction +
regime gates the full DL detector uses, but skip the candle-2
confirmation (we don't have it yet — we won't until 10:30). Symbols
that pass are "armed for 10:30" and emit a ``lock1_scouted`` alert
giving the operator 30 minutes of advance notice.

This is NOT a separate strategy. It's a privileged peek into the
intermediate state of ``double_lock_filtered``. If lock 1 is set on
AAPL at 10:00, then a second-candle confirmation at 10:30 will fire
the full strategy on the exact same symbol.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import time as dtime
from typing import Any, Literal

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Lock1Candidate:
    symbol: str
    direction: Literal["long", "short"]
    candle_close: float          # candle-1 close price (= probable entry context)
    candle_body_pct: float       # body / range of candle 1
    candle_close_pct: float      # close-position within range
    volume_ratio: float          # c1 volume / slot median
    rsi_d: float
    adx_d: float
    vix_prev_close: float
    notes: str = ""


def evaluate_lock1(
    *,
    symbol: str,
    bars_30m: pd.DataFrame,
    daily: pd.DataFrame,
    vix_prev_close: float | None,
    config: dict[str, Any],
    as_of_ts: pd.Timestamp,
) -> Lock1Candidate | None:
    """Return a Lock1Candidate when candle-1 + regime gates pass, else None.

    Mirrors the candle-1 + regime portion of
    ``agents.detectors.double_lock_filtered`` so the two can never
    drift — anything the scout flags here is exactly what the full
    detector will accept tomorrow morning... assuming candle 2 confirms.
    """
    t = config.get("thresholds", {}) or {}
    body_pct_thr  = float(t.get("body_pct", 0.5))
    press_hi      = float(t.get("press_hi", 0.5))
    press_lo      = float(t.get("press_lo", 0.5))
    vol_mult      = float(t.get("vol_mult", 1.2))
    vix_min       = float(t.get("vix_min", 20.0))
    adx_max       = float(t.get("adx_max", 35.0))
    rsi_long_lo   = float(t.get("rsi_long_lo", 40.0))
    rsi_long_hi   = float(t.get("rsi_long_hi", 65.0))
    rsi_short_lo  = float(t.get("rsi_short_lo", 20.0))
    rsi_short_hi  = float(t.get("rsi_short_hi", 40.0))

    if as_of_ts is None or as_of_ts.tzinfo is None:
        return None
    as_of_et = as_of_ts.tz_convert("America/New_York")
    today = as_of_et.date()

    bars_30m = bars_30m[bars_30m.index <= as_of_ts]
    today_bars = bars_30m[bars_30m.index.date == today]
    if len(today_bars) < 1:
        return None

    c1 = today_bars.iloc[0]
    if c1.name.time() != dtime(9, 30):
        return None

    o1, h1, l1, cl1, v1 = (
        float(c1["open"]), float(c1["high"]),
        float(c1["low"]),  float(c1["close"]),
        float(c1["volume"]),
    )
    rng1 = h1 - l1
    if rng1 <= 0:
        return None

    body = abs(cl1 - o1) / rng1
    cp   = (cl1 - l1) / rng1   # close position within range

    same_slot = bars_30m[bars_30m.index.time == dtime(9, 30)]
    slot_med = float(same_slot["volume"].median()) if len(same_slot) else 0.0
    if slot_med <= 0:
        return None
    vol_ratio = v1 / slot_med

    bull_lock = (
        cl1 > o1 and body >= body_pct_thr
        and cp >= press_hi and vol_ratio >= vol_mult
    )
    bear_lock = (
        cl1 < o1 and body >= body_pct_thr
        and cp <= press_lo and vol_ratio >= vol_mult
    )
    if bull_lock:
        direction: Literal["long", "short"] = "long"
    elif bear_lock:
        direction = "short"
    else:
        return None

    if vix_prev_close is None or vix_prev_close < vix_min:
        return None

    today_ts = pd.Timestamp(today)
    prev_idx = daily.index[daily.index < today_ts]
    if len(prev_idx) == 0:
        return None
    prev_daily = daily.loc[prev_idx[-1]]
    rsi_d = (
        float(prev_daily.get("rsi_14"))
        if pd.notna(prev_daily.get("rsi_14")) else None
    )
    adx_d = (
        float(prev_daily.get("adx_14"))
        if pd.notna(prev_daily.get("adx_14")) else None
    )
    if rsi_d is None or adx_d is None:
        return None

    if adx_d > adx_max:
        return None
    if direction == "long":
        if not (rsi_long_lo <= rsi_d <= rsi_long_hi):
            return None
    else:
        if not (rsi_short_lo <= rsi_d <= rsi_short_hi):
            return None

    return Lock1Candidate(
        symbol=symbol,
        direction=direction,
        candle_close=round(cl1, 2),
        candle_body_pct=round(body, 3),
        candle_close_pct=round(cp, 3),
        volume_ratio=round(vol_ratio, 2),
        rsi_d=round(rsi_d, 2),
        adx_d=round(adx_d, 2),
        vix_prev_close=round(vix_prev_close, 2),
    )
