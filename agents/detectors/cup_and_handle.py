"""Cup and Handle detector.

Spec (bullish continuation):
  1. Prior uptrend of ≥ 30% before the cup.
  2. Cup: rounded U-shape, 15–50% depth from pivot, 35–325 trading days
     (7–65 weeks). The left-side decline and right-side recovery should
     be roughly symmetrical (right-side bars ≥ 50% of left-side bars).
  3. Right side of the cup recovers to within 5% of the pivot.
  4. Handle: 1–8 weeks, pulls back 8–20% from pivot, drifts sideways or
     slightly down (not up), forms in the upper half of the cup.
  5. Trigger: latest close > pivot on volume ≥ 1.5× 20-bar avg.

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

PATTERN_NAME = "cup_and_handle"

# Cup + handle needs a long bar history — 325 days + buffer for prior uptrend.
MIN_BARS = 400


def detect_cup_and_handle(
    daily: pd.DataFrame,
    hourly: pd.DataFrame,
    config: dict,
    as_of_ts: pd.Timestamp,
    macro_context: dict | None = None,
) -> PatternResult | None:
    daily = slice_as_of(daily, as_of_ts)
    if len(daily) < MIN_BARS:
        return None

    thresholds = (config.get("pattern_thresholds") or {}).get("cup_and_handle", {})
    cup_depth_min_pct = float(thresholds.get("cup_depth_min_pct", 15.0))
    cup_depth_max_pct = float(thresholds.get("cup_depth_max_pct", 50.0))
    cup_duration_min = int(thresholds.get("cup_duration_min_weeks", 7)) * 5
    cup_duration_max = 65 * 5
    handle_depth_max_pct = float(thresholds.get("handle_depth_max_pct", 20.0))
    vol_min = float(thresholds.get("breakout_volume_ratio_min", 1.5))

    window = daily.tail(400).copy().reset_index(drop=True)
    last = window.iloc[-1]
    last_close = float(last["close"])
    atr = safe(last, "atr_14")
    if pd.isna(atr) or atr <= 0:
        return None

    # Trigger volume must be present regardless of structure
    volume_ratio = safe(last, "volume_ratio")
    if pd.isna(volume_ratio) or volume_ratio < vol_min:
        return None

    # Step 1: the pivot is the highest bar in the look-back window EXCEPT
    # the current breakout bar. Scan within [-cup_duration_max, -10] for
    # the high that would be "the rim of the cup."
    search_start = max(0, len(window) - cup_duration_max - 10)
    search_end = len(window) - 10  # handle must be ≥ few bars long
    if search_end - search_start < cup_duration_min:
        return None
    pivot_window = window.iloc[search_start:search_end]
    pivot_i = int(pivot_window["high"].idxmax())
    pivot_price = float(window["high"].iloc[pivot_i])
    if pivot_price <= 0:
        return None

    # Breakout requires last close above the pivot
    if last_close <= pivot_price * 1.001:
        return None

    # Step 2: cup low is the lowest point between pivot and now
    post_pivot = window.iloc[pivot_i + 1:]
    if post_pivot.empty:
        return None
    cup_low_i = int(post_pivot["low"].idxmin())
    cup_low_price = float(window["low"].iloc[cup_low_i])
    cup_depth_pct = (pivot_price - cup_low_price) / pivot_price * 100.0
    if not (cup_depth_min_pct <= cup_depth_pct <= cup_depth_max_pct):
        return None

    # Step 3: cup duration
    cup_duration = len(window) - 1 - pivot_i
    if not (cup_duration_min <= cup_duration <= cup_duration_max):
        return None

    # Step 4: U-shape check (right-side recovery bars ≥ 50% of left-side)
    left_bars = cup_low_i - pivot_i
    right_bars = (len(window) - 1) - cup_low_i
    if left_bars <= 0 or right_bars <= 0:
        return None
    shape_ratio = right_bars / left_bars
    if shape_ratio < 0.5:
        return None  # V-shape

    # Step 5: prior uptrend — 30%+ rally in the bars BEFORE the pivot.
    # Look back 60 bars from the pivot for a prior low.
    prior_start = max(0, pivot_i - 60)
    if prior_start >= pivot_i:
        return None
    prior_low = float(window["low"].iloc[prior_start:pivot_i].min())
    if prior_low <= 0:
        return None
    prior_rise = (pivot_price - prior_low) / prior_low * 100.0
    if prior_rise < 30.0:
        return None

    # Step 6: handle identification.
    # Handle is the recent pullback after the right-side of the cup
    # recovered near the pivot. Find the bar where price first got
    # within 5% of the pivot on the right side, treat bars after that
    # up to the current trigger as handle candidates.
    right_side = window.iloc[cup_low_i + 1:]
    rim_touch_rel = right_side[right_side["high"] >= pivot_price * 0.95]
    if rim_touch_rel.empty:
        return None
    rim_i = int(rim_touch_rel.index[0])
    handle_slice = window.iloc[rim_i + 1:-1]  # exclude breakout bar
    if handle_slice.empty:
        return None
    handle_low = float(handle_slice["low"].min())
    handle_depth_pct = (pivot_price - handle_low) / pivot_price * 100.0
    if handle_depth_pct > handle_depth_max_pct:
        return None  # handle too deep
    # Handle must form in upper half of the cup (above midpoint)
    cup_midpoint = cup_low_price + (pivot_price - cup_low_price) / 2.0
    if handle_low < cup_midpoint:
        return None

    # Levels
    cup_height = pivot_price - cup_low_price
    stop = handle_low - 0.1 * atr
    if last_close - stop <= 0.01:
        return None
    tp1 = pivot_price + cup_height * 0.75
    tp2 = pivot_price + cup_height * 1.00

    pqs_base = 62
    modifiers: dict[str, int] = {
        "prior_uptrend": min(10, int((prior_rise - 30) / 10) * 2 + 3),
        "ideal_cup_duration": 8 if 35 <= cup_duration <= 130 else 0,
        "rounded_shape": 8 if shape_ratio >= 0.75 else 4,
    }
    if cup_depth_pct > 40.0:
        modifiers["too_deep_cup"] = -10

    apply_universal_modifiers(
        modifiers, row=last, direction="long", macro_context=macro_context,
    )
    pqs_total = cap_pqs(pqs_base, modifiers)

    return PatternResult(
        pattern_name=PATTERN_NAME,
        direction="long",
        pqs_base=pqs_base,
        pqs_modifiers=modifiers,
        pqs_total=pqs_total,
        entry_price=round(last_close, 2),
        stop_price=round(stop, 2),
        tp1_price=round(tp1, 2),
        tp2_price=round(tp2, 2),
        invalidation_level=round(stop, 2),
        invalidation_condition="daily_close_below_handle_low",
        evidence_items=[
            {"type": "pattern",
             "ref": f"cup: pivot {pivot_price:.2f}, low {cup_low_price:.2f}, "
                     f"depth {cup_depth_pct:.1f}%, {cup_duration} bars"},
            {"type": "pattern",
             "ref": f"shape ratio right/left = {shape_ratio:.2f} (U-shape)"},
            {"type": "pattern",
             "ref": f"handle low {handle_low:.2f}, depth {handle_depth_pct:.1f}% of pivot"},
            {"type": "pattern",
             "ref": f"prior uptrend {prior_rise:.1f}% before pivot"},
            {"type": "indicator",
             "ref": f"breakout close {last_close:.2f} > pivot on {volume_ratio:.2f}× volume"},
        ],
    )
