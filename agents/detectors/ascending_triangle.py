"""Ascending / Descending Triangle detector.

Ascending triangle — spec:
  * At least ``min_resistance_touches`` (default 2) touches of a near-flat
    resistance level; touches within ±``resistance_tolerance_pct`` of
    each other (default 0.5%).
  * At least 2 rising swing lows between those touches — linear-regression
    slope of the lows must be positive and meaningful.
  * Pattern duration: 10–60 bars.
  * Trigger: latest close > resistance on volume ≥
    ``breakout_volume_ratio_min``.
  * Breakout position within the pattern's 10–60 bar lifespan matters
    (ideal 50–75% through, too-early gets a penalty).

Descending triangle is the mirror.

Pure function of (daily, hourly, config, as_of_ts).
"""
from __future__ import annotations

import pandas as pd

from agents.detectors._helpers import (
    apply_universal_modifiers,
    cap_pqs,
    safe,
    slice_as_of,
    swing_high_indices,
    swing_low_indices,
)
from models.pattern import PatternResult

PATTERN_NAME = "ascending_triangle"


def _linreg_slope(values: list[float]) -> float:
    """Ordinary-least-squares slope of a tiny series. Pure and dep-free."""
    n = len(values)
    if n < 2:
        return 0.0
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(values) / n
    num = sum((xs[i] - x_mean) * (values[i] - y_mean) for i in range(n))
    den = sum((xs[i] - x_mean) ** 2 for i in range(n))
    return num / den if den else 0.0


def _try_ascending(
    window: pd.DataFrame, thresh: dict, macro: dict | None,
) -> PatternResult | None:
    min_touches = int(thresh.get("min_resistance_touches", 2))
    tol_pct = float(thresh.get("resistance_tolerance_pct", 0.5))
    vol_min = float(thresh.get("breakout_volume_ratio_min", 1.5))

    # Highs candidates within the last 60 bars
    highs_idx = [i for i in swing_high_indices(window["high"]) if i >= len(window) - 60]
    if len(highs_idx) < min_touches:
        return None

    # Find the flattest resistance cluster: pick the N highest swings that
    # are within tolerance of each other.
    vals = [(i, float(window["high"].iloc[i])) for i in highs_idx]
    # Sort by price desc, take top 4 candidates, then find clusters within tolerance.
    vals.sort(key=lambda x: -x[1])
    cluster: list[tuple[int, float]] = []
    for i, v in vals:
        if not cluster:
            cluster.append((i, v))
            continue
        top = cluster[0][1]
        if abs(v - top) / max(top, 1e-6) * 100.0 <= tol_pct:
            cluster.append((i, v))
    if len(cluster) < min_touches:
        return None
    resistance = sum(v for _, v in cluster) / len(cluster)
    cluster_indices = sorted(i for i, _ in cluster)
    first_touch_i = cluster_indices[0]
    last_touch_i = cluster_indices[-1]
    if last_touch_i - first_touch_i < 10:
        return None

    # Rising lows between first touch and last touch
    lows_between = [
        i for i in swing_low_indices(window["low"])
        if first_touch_i <= i <= last_touch_i
    ]
    if len(lows_between) < 2:
        return None
    low_values = [float(window["low"].iloc[i]) for i in lows_between]
    slope = _linreg_slope(low_values)
    if slope <= 0:
        return None

    # Trigger: latest close must break resistance
    last_close = float(window["close"].iloc[-1])
    if last_close <= resistance:
        return None

    last = window.iloc[-1]
    volume_ratio = safe(last, "volume_ratio")
    if pd.isna(volume_ratio) or volume_ratio < vol_min:
        return None

    atr = safe(last, "atr_14")
    if pd.isna(atr) or atr <= 0:
        return None

    # Levels
    most_recent_low = low_values[-1]
    stop = most_recent_low - 0.1 * atr
    pattern_height = resistance - low_values[0]
    if pattern_height <= 0 or last_close - stop <= 0.01:
        return None
    tp1 = resistance + pattern_height * 0.75
    tp2 = resistance + pattern_height * 1.00

    # Where in the triangle's lifespan did the breakout occur?
    life_start = first_touch_i
    life_end = last_touch_i
    # Breakout bar is the last bar of the window
    breakout_i = len(window) - 1
    span = max(life_end - life_start, 1)
    offset = (breakout_i - life_start) / span

    pqs_base = 60
    modifiers: dict[str, int] = {
        "breakout_confirmed": 8,
        "touches": 15 if len(cluster) >= 4 else (10 if len(cluster) >= 3 else 0),
    }
    if 0.25 <= offset <= 1.25:
        modifiers["ideal_breakout_zone"] = 10
    else:
        modifiers["early_breakout_penalty"] = -15

    apply_universal_modifiers(
        modifiers, row=last, direction="long", macro_context=macro,
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
        invalidation_condition="close_below_most_recent_rising_low",
        evidence_items=[
            {"type": "pattern",
             "ref": f"ascending triangle: {len(cluster)} resistance touches @ {resistance:.2f}"},
            {"type": "pattern",
             "ref": f"rising lows ({len(lows_between)} swings, slope {slope:.4f})"},
            {"type": "indicator",
             "ref": f"breakout close {last_close:.2f} > resistance {resistance:.2f} on {volume_ratio:.2f}× volume"},
        ],
    )


def _try_descending(
    window: pd.DataFrame, thresh: dict, macro: dict | None,
) -> PatternResult | None:
    # Mirror of ascending: flat support, declining highs, breakdown trigger.
    min_touches = int(thresh.get("min_resistance_touches", 2))
    tol_pct = float(thresh.get("resistance_tolerance_pct", 0.5))
    vol_min = float(thresh.get("breakout_volume_ratio_min", 1.5))

    lows_idx = [i for i in swing_low_indices(window["low"]) if i >= len(window) - 60]
    if len(lows_idx) < min_touches:
        return None

    vals = [(i, float(window["low"].iloc[i])) for i in lows_idx]
    vals.sort(key=lambda x: x[1])  # lowest first
    cluster: list[tuple[int, float]] = []
    for i, v in vals:
        if not cluster:
            cluster.append((i, v))
            continue
        bot = cluster[0][1]
        if abs(v - bot) / max(bot, 1e-6) * 100.0 <= tol_pct:
            cluster.append((i, v))
    if len(cluster) < min_touches:
        return None
    support = sum(v for _, v in cluster) / len(cluster)
    cluster_indices = sorted(i for i, _ in cluster)
    first_i = cluster_indices[0]
    last_i = cluster_indices[-1]
    if last_i - first_i < 10:
        return None

    highs_between = [
        i for i in swing_high_indices(window["high"])
        if first_i <= i <= last_i
    ]
    if len(highs_between) < 2:
        return None
    high_values = [float(window["high"].iloc[i]) for i in highs_between]
    slope = _linreg_slope(high_values)
    if slope >= 0:
        return None

    last_close = float(window["close"].iloc[-1])
    if last_close >= support:
        return None

    last = window.iloc[-1]
    volume_ratio = safe(last, "volume_ratio")
    if pd.isna(volume_ratio) or volume_ratio < vol_min:
        return None
    atr = safe(last, "atr_14")
    if pd.isna(atr) or atr <= 0:
        return None

    most_recent_high = high_values[-1]
    stop = most_recent_high + 0.1 * atr
    pattern_height = high_values[0] - support
    if pattern_height <= 0 or stop - last_close <= 0.01:
        return None
    tp1 = support - pattern_height * 0.75
    tp2 = support - pattern_height * 1.00

    pqs_base = 60
    modifiers: dict[str, int] = {
        "breakout_confirmed": 8,
        "touches": 15 if len(cluster) >= 4 else (10 if len(cluster) >= 3 else 0),
    }

    apply_universal_modifiers(
        modifiers, row=last, direction="short", macro_context=macro,
    )
    pqs_total = cap_pqs(pqs_base, modifiers)

    return PatternResult(
        pattern_name="descending_triangle",
        direction="short",
        pqs_base=pqs_base,
        pqs_modifiers=modifiers,
        pqs_total=pqs_total,
        entry_price=round(last_close, 2),
        stop_price=round(stop, 2),
        tp1_price=round(tp1, 2),
        tp2_price=round(tp2, 2),
        invalidation_level=round(stop, 2),
        invalidation_condition="close_above_most_recent_declining_high",
        evidence_items=[
            {"type": "pattern",
             "ref": f"descending triangle: {len(cluster)} support touches @ {support:.2f}"},
            {"type": "pattern",
             "ref": f"declining highs ({len(highs_between)} swings, slope {slope:.4f})"},
        ],
    )


def detect_ascending_descending_triangle(
    daily: pd.DataFrame,
    hourly: pd.DataFrame,
    config: dict,
    as_of_ts: pd.Timestamp,
    macro_context: dict | None = None,
) -> PatternResult | None:
    daily = slice_as_of(daily, as_of_ts)
    if len(daily) < 100:
        return None

    thresholds = (config.get("pattern_thresholds") or {}).get("ascending_triangle", {})
    window = daily.tail(80).copy().reset_index(drop=False)

    asc = _try_ascending(window, thresholds, macro_context)
    desc = _try_descending(window, thresholds, macro_context)
    if asc and desc:
        return asc if asc.pqs_total >= desc.pqs_total else desc
    return asc or desc
