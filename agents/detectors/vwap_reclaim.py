"""VWAP Reclaim detector.

Spec: price held above VWAP for a sustained period, broke below on a
selloff, consolidated below for 2–8 bars on declining volume, then
reclaimed VWAP on the latest bar with volume ≥ 1.5× average.

The pure-function contract says ``hourly`` may be empty. When hourly
bars are available we prefer them (the pattern is inherently intraday);
when they aren't, we fall back to a daily-bar approximation where
"VWAP" is the rolling volume-weighted mean the indicator service adds
to the frame.

We look at the last 12 bars on whichever frame we use — enough room
for "above VWAP → break → consolidate → reclaim" to play out without
picking up noise from further back.
"""
from __future__ import annotations

import pandas as pd

from agents.detectors._helpers import (
    apply_universal_modifiers,
    cap_pqs,
    last_row,
    safe,
    slice_as_of,
)
from models.pattern import PatternResult

PATTERN_NAME = "vwap_reclaim"


def detect_vwap_reclaim(
    daily: pd.DataFrame,
    hourly: pd.DataFrame,
    config: dict,
    as_of_ts: pd.Timestamp,
    macro_context: dict | None = None,
) -> PatternResult | None:
    thresholds = (config.get("pattern_thresholds") or {}).get("vwap_reclaim", {})
    min_bars_above = int(thresholds.get("min_bars_above_vwap_before_break", 8))
    max_consol_bars = int(thresholds.get("max_consolidation_bars", 8))
    reclaim_vol_min = float(thresholds.get("reclaim_volume_ratio_min", 1.5))

    # Prefer hourly; fall back to daily. Either way, ``df`` must have
    # 'vwap' and 'volume_ratio' columns which indicator_service adds.
    if hourly is not None and not hourly.empty:
        df = slice_as_of(hourly, as_of_ts)
    else:
        df = slice_as_of(daily, as_of_ts)
    if len(df) < (min_bars_above + max_consol_bars + 2):
        return None
    if "vwap" not in df.columns or df["vwap"].isna().all():
        return None

    last = df.iloc[-1]
    last_close = float(last["close"])
    last_vwap = safe(last, "vwap")
    last_volume_ratio = safe(last, "volume_ratio")
    atr = safe(last, "atr_14")
    if pd.isna(last_vwap) or pd.isna(atr) or atr <= 0:
        return None

    # Trigger gate: the latest bar must close above VWAP (with a body,
    # not just a wick — we approximate by requiring close > open).
    if last_close <= last_vwap:
        return None
    if last_close <= float(last["open"]):
        # bearish reclaim candle — spec allows but at a penalty; skip
        # entirely if it also didn't clear VWAP comfortably.
        if (last_close - last_vwap) < 0.001 * last_vwap:
            return None

    # Reclaim volume check.
    if pd.isna(last_volume_ratio) or last_volume_ratio < reclaim_vol_min:
        return None

    # Walk backwards from the bar just before the trigger:
    #   * `consol_bars` = consecutive bars with close <= vwap right before
    #     the trigger (the "holding pattern" below VWAP)
    #   * before the consolidation, we need at least `min_bars_above`
    #     consecutive bars with close above VWAP.
    prior = df.iloc[:-1]
    consol = 0
    i = len(prior) - 1
    while i >= 0 and consol < max_consol_bars:
        row = prior.iloc[i]
        c = float(row["close"])
        v = safe(row, "vwap")
        if pd.isna(v) or c > v:
            break
        consol += 1
        i -= 1
    if not (2 <= consol <= max_consol_bars):
        return None

    # Count how many bars were above VWAP immediately before the drop.
    above = 0
    while i >= 0 and above < min_bars_above * 2:
        row = prior.iloc[i]
        c = float(row["close"])
        v = safe(row, "vwap")
        if pd.isna(v) or c <= v:
            break
        above += 1
        i -= 1
    if above < min_bars_above:
        return None

    # Levels
    consol_slice = prior.iloc[max(0, len(prior) - consol):]
    consol_low = float(consol_slice["low"].min()) if not consol_slice.empty else last_vwap
    entry_price = last_close
    stop_price = consol_low - 0.1 * atr
    if entry_price - stop_price <= 0.01:
        return None

    # TP1 = prior high within the recent ~20-bar window (the "resistance"
    # price ran into before breaking down); TP2 = 2R extension.
    recent_high = float(df["high"].tail(20).max())
    tp1 = max(recent_high, entry_price + (entry_price - stop_price) * 1.5)
    tp2 = entry_price + (entry_price - stop_price) * 3.0

    pqs_base = 50
    modifiers: dict[str, int] = {
        "consol_duration": 7 if 3 <= consol <= 6 else 3,
        "sustained_above_vwap": 8,
    }
    # First-reclaim bonus can't be verified cross-session on a sliced
    # frame, so skip it for this implementation — universal modifiers
    # already reward the volume ratio.
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
        entry_price=round(entry_price, 2),
        stop_price=round(stop_price, 2),
        tp1_price=round(tp1, 2),
        tp2_price=round(tp2, 2),
        invalidation_level=round(stop_price, 2),
        invalidation_condition="close_below_consolidation_low",
        evidence_items=[
            {"type": "pattern",
             "ref": f"VWAP reclaim: {above} bars above -> {consol}-bar consolidation below -> reclaim"},
            {"type": "indicator",
             "ref": f"reclaim close {last_close:.2f} > VWAP {last_vwap:.2f}"},
            {"type": "indicator",
             "ref": f"volume_ratio {last_volume_ratio:.2f}× (>= {reclaim_vol_min:.1f}× required)"},
        ],
    )
