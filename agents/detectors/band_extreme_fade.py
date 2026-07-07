"""Band Extreme Fade — Bollinger 3-sigma "Extreme Fade" mean reversion (video FqxEKDxemtI).

A rubber-band snap-back: price stretches to 3 standard deviations below the 20-SMA (an extreme),
then we wait for it to close back INSIDE the 2-sigma band (confirmation the reversion has begun)
and fade toward the mean. Validated on daily US stocks (OOS PF 1.22-1.40, +0.14/+0.28R) and
gated as a DIVERSIFIER (0.54 corr to Fear-Dip, and only 0.22 to the other new mean-rev sleeve
RSI Pullback). See strategies/strategy_docs/BAND_EXTREME_FADE.md and STRATEGY_GRID.md.

Rules (long):
  * A bar within the last `arm_lookback` bars closed BELOW the 3-sigma lower band (extreme).
  * The current bar closes back ABOVE the 2-sigma lower band (bb_lower_20) AND below the basis.
  * Entry next open; stop below the recent swing low; TARGET the basis (20-SMA).

The 3-sigma band is derived from the standard 2-sigma Bollinger columns:
  std = (bb_upper_20 - sma_20) / 2 ; lower_3sigma = sma_20 - 3*std.

Pure function of (daily, hourly, config, as_of_ts, macro_context) -> PatternResult.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from agents.detectors._helpers import apply_universal_modifiers, cap_pqs, safe, slice_as_of
from models.pattern import PatternResult

PATTERN_NAME = "band_extreme_fade"


def detect_band_extreme_fade(daily, hourly, config, as_of_ts, macro_context=None):
    th = (config.get("pattern_thresholds") or {}).get(PATTERN_NAME, {})
    arm_lookback = int(th.get("arm_lookback", 10))
    swing_lookback = int(th.get("swing_lookback", 5))
    stop_buffer_atr = float(th.get("stop_buffer_atr", 0.1))

    df = slice_as_of(daily, as_of_ts)
    if df is None or len(df) < 60:
        return None
    last = df.iloc[-1]
    close = float(last["close"])
    atr = safe(last, "atr_14")
    sma20 = safe(last, "sma_20")
    bb_lo2 = safe(last, "bb_lower_20")
    bb_up2 = safe(last, "bb_upper_20")
    if any(pd.isna(x) for x in (atr, sma20, bb_lo2, bb_up2)) or atr <= 0 or sma20 <= 0:
        return None

    # Confirmation: current close back inside the 2-sigma band but still below the mean.
    if not (close > bb_lo2 and close < sma20):
        return None

    # Armed? some bar in the recent window closed below its own 3-sigma lower band.
    win = df.iloc[-(arm_lookback + 1):-1]  # exclude the current (confirmation) bar
    if len(win) < 2:
        return None
    std = (win["bb_upper_20"] - win["sma_20"]) / 2.0
    lower3 = win["sma_20"] - 3.0 * std
    armed = bool((win["close"] < lower3).any())
    if not armed:
        return None

    lows = df["low"].values[-swing_lookback:]
    entry_price = close
    stop_price = float(lows.min()) - stop_buffer_atr * atr
    risk = entry_price - stop_price
    if risk <= 0.01 or sma20 <= entry_price:
        return None
    tp2 = sma20                                   # target the basis (mean)
    tp1 = entry_price + max(0.6 * (sma20 - entry_price), 1.0 * risk)
    if tp1 >= tp2:
        tp1 = entry_price + 0.5 * (sma20 - entry_price)

    # how deep was the excursion (in sigma), for scoring
    cur_std = (bb_up2 - sma20) / 2.0
    depth_sigma = (sma20 - float(win["close"].min())) / cur_std if cur_std > 0 else 0.0

    pqs_base = 57
    modifiers: dict[str, int] = {}
    if depth_sigma >= 3.5:
        modifiers["deep_extreme"] = 10
    elif depth_sigma >= 3.0:
        modifiers["extreme"] = 6
    sma200 = safe(last, "sma_200")
    if not pd.isna(sma200) and close > sma200:
        modifiers["uptrend_dip"] = 6
    rsi = safe(last, "rsi_14")
    if not pd.isna(rsi) and rsi <= 30:
        modifiers["oversold_rsi"] = 5
    apply_universal_modifiers(modifiers, row=last, direction="long", macro_context=macro_context)
    pqs_total = cap_pqs(pqs_base, modifiers)

    return PatternResult(
        pattern_name=PATTERN_NAME, direction="long",
        pqs_base=pqs_base, pqs_modifiers=modifiers, pqs_total=pqs_total,
        entry_price=round(entry_price, 2), stop_price=round(stop_price, 2),
        tp1_price=round(tp1, 2), tp2_price=round(tp2, 2),
        invalidation_level=round(stop_price, 2),
        invalidation_condition="close_below_swing_stop_or_reaches_basis",
        evidence_items=[
            {"type": "pattern", "ref": f"3-sigma stretch (~{depth_sigma:.1f}sigma below SMA20) then close back inside 2-sigma band ({close:.2f} > lower2 {bb_lo2:.2f})"},
            {"type": "filter", "ref": f"Below the basis SMA20 {sma20:.2f} — fading toward the mean"},
            {"type": "indicator", "ref": f"target = basis {sma20:.2f}; stop {stop_price:.2f} (swing low - {stop_buffer_atr:.1f}xATR)"},
            {"type": "note", "ref": "Bollinger 3SD Extreme Fade (FqxEKDxemtI). Equities edge only — FX intraday fails (band-hugging). Diversifier vs Fear-Dip (corr 0.54)."},
        ],
    )
