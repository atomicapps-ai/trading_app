"""Inside Bar / NR7 compression detector.

Inside bar (day N):
    high[N]  < high[N-1]   AND   low[N] > low[N-1]

NR7 (day N):
    range[N] = high[N] - low[N] is the smallest of the last 7 days

Trigger (we treat the last bar as both the inside+NR7 bar AND the
trigger bar — i.e. the setup has just formed; the next session is the
break-out day). Direction is decided by the prior trend (close vs
sma_50) — a pullback inside bar above sma_50 is a long continuation
setup; below sma_50 is a short continuation.

Entry: mother-candle extreme + 1 tick (long = high+0.01, short = low-0.01)
Stop:  opposite extreme of the mother candle
Targets: measured move (mother candle range) 1x and 2x

Pure function of (daily, hourly, config, as_of_ts).
"""
from __future__ import annotations

import pandas as pd

from agents.detectors._helpers import (
    apply_universal_modifiers,
    cap_pqs,
    safe,
    slice_as_of,
)
from models.pattern import PatternResult

PATTERN_NAME = "inside_bar_nr7"


def detect_inside_bar_nr7(
    daily: pd.DataFrame,
    hourly: pd.DataFrame,
    config: dict,
    as_of_ts: pd.Timestamp,
    macro_context: dict | None = None,
) -> PatternResult | None:
    daily = slice_as_of(daily, as_of_ts)
    if len(daily) < 60:
        return None

    thresholds = (config.get("pattern_thresholds") or {}).get("inside_bar_nr7", {})
    mother_min_atr_ratio = float(thresholds.get("mother_candle_min_atr_ratio", 0.75))

    # Last bar is the candidate inside+NR7 bar. The bar before it is the
    # mother candle (whose high/low define the breakout levels).
    last = daily.iloc[-1]
    mother = daily.iloc[-2]
    last_high = float(last["high"])
    last_low = float(last["low"])
    last_close = float(last["close"])
    last_range = last_high - last_low

    mother_high = float(mother["high"])
    mother_low = float(mother["low"])
    mother_range = mother_high - mother_low

    # Inside bar: strictly inside the mother candle
    inside = last_high < mother_high and last_low > mother_low
    if not inside:
        return None

    # NR7: smallest range of the last 7 bars (mother is last.shift(-1))
    last7 = daily.tail(7)
    if last_range > 0 and last_range < last7["high"].sub(last7["low"]).drop(last.name).min():
        is_nr7 = True
    else:
        is_nr7 = last_range == float(last7["high"].sub(last7["low"]).min())
    if not is_nr7:
        return None

    # Mother candle must have meaningful range — a tiny one produces a
    # degenerate setup with tight stop / tiny target.
    atr = safe(last, "atr_14")
    if pd.isna(atr) or atr <= 0:
        return None
    if mother_range < mother_min_atr_ratio * atr:
        return None

    # Direction from prior trend
    sma50 = safe(last, "sma_50")
    if pd.isna(sma50):
        return None
    direction: str = "long" if last_close > sma50 else "short"

    if direction == "long":
        entry_price = mother_high + 0.01
        stop_price = mother_low - 0.01
        measured_move = mother_range
        tp1 = entry_price + measured_move
        tp2 = entry_price + 2 * measured_move
        invalidation_level = mother_low
        invalidation_condition = "daily_close_below_mother_low"
    else:
        entry_price = mother_low - 0.01
        stop_price = mother_high + 0.01
        measured_move = mother_range
        tp1 = entry_price - measured_move
        tp2 = entry_price - 2 * measured_move
        invalidation_level = mother_high
        invalidation_condition = "daily_close_above_mother_high"

    pqs_base = 50
    modifiers: dict[str, int] = {
        "inside_bar": 10,
        "nr7_compression": 8,
    }
    apply_universal_modifiers(
        modifiers, row=last, direction=direction,  # type: ignore[arg-type]
        macro_context=macro_context,
    )
    pqs_total = cap_pqs(pqs_base, modifiers)

    evidence = [
        {"type": "pattern", "ref": "inside bar (high & low both inside prior bar)"},
        {"type": "pattern", "ref": f"NR7: range={last_range:.2f} is narrowest of last 7"},
        {"type": "pattern", "ref": f"mother range {mother_range:.2f} ({mother_range/atr:.2f} ATR)"},
    ]

    return PatternResult(
        pattern_name=PATTERN_NAME,
        direction=direction,  # type: ignore[arg-type]
        pqs_base=pqs_base,
        pqs_modifiers=modifiers,
        pqs_total=pqs_total,
        entry_price=round(entry_price, 2),
        stop_price=round(stop_price, 2),
        tp1_price=round(tp1, 2),
        tp2_price=round(tp2, 2),
        invalidation_level=round(invalidation_level, 2),
        invalidation_condition=invalidation_condition,
        evidence_items=evidence,
    )
