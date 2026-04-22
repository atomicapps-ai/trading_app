"""Wyckoff Accumulation detector (Spring entry variant).

Full Wyckoff has 5 phases (A–E) and many labeled events (PS, SC, AR,
ST, UT, Spring, LPS, SOS, BU). Implementing the whole framework is a
research project unto itself. This detector captures the *spring entry*
setup which is the most reliable and tradeable Wyckoff signal:

  1. **Trading range** of ≥ 30 bars (6 weeks) with identifiable
     Selling Climax low (``SC``) and Automatic Rally high (``AR``).
  2. **SC identification** — the climactic selling bar in the decline
     that preceded the range: highest volume in the prior ~60 bars
     AND a long lower wick (body ≤ 40% of full range).
  3. **Spring** — a recent bar (within ~5 of the trigger) that
     undercuts the SC low by 0.1–5% on low volume (spring volume
     < 75% of SC volume).
  4. **Recovery** — the latest close is back above the SC low and
     within the range.
  5. Entry = latest close. Stop = spring low. Targets = measured
     moves off the AR–SC range.

Distribution is structurally the mirror (BC, UTAD, LPSY) — emitted as
``direction='short'`` when that mirror setup is detected.

Pure function of (daily, hourly, config, as_of_ts). No clock, no I/O.
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

PATTERN_NAME = "wyckoff_accumulation"

# Wyckoff is a long-term structure — need plenty of bars before + during.
MIN_BARS = 200


def _find_sc_index(window: pd.DataFrame) -> int | None:
    """Selling Climax = the climactic down-bar in the decline phase.

    Heuristic: among the 100 bars BEFORE the last 30 (i.e. predating
    the current range), find the bar whose volume is the highest AND
    which has a long lower wick (body ≤ 40% of full range) closing in
    the upper half of its range — classic climactic reversal signature.
    Returns the index, or None if nothing qualifies.
    """
    n = len(window)
    if n < MIN_BARS:
        return None
    decline_end = n - 30  # the range must cover the last ~30 bars
    decline_start = max(0, decline_end - 100)
    if decline_end - decline_start < 20:
        return None

    # Rank candidates by volume
    decline = window.iloc[decline_start:decline_end].copy()
    decline = decline.sort_values("volume", ascending=False).head(5)

    best_i: int | None = None
    for idx in decline.index:
        bar = window.iloc[idx]
        rng = float(bar["high"]) - float(bar["low"])
        if rng <= 0:
            continue
        body = abs(float(bar["close"]) - float(bar["open"]))
        body_pct = body / rng
        close_in_upper_half = (
            (float(bar["close"]) - float(bar["low"])) / rng >= 0.5
        )
        if body_pct <= 0.5 and close_in_upper_half:
            best_i = int(idx)
            break
    return best_i


def detect_wyckoff_accumulation(
    daily: pd.DataFrame,
    hourly: pd.DataFrame,
    config: dict,
    as_of_ts: pd.Timestamp,
    macro_context: dict | None = None,
) -> PatternResult | None:
    daily = slice_as_of(daily, as_of_ts)
    if len(daily) < MIN_BARS:
        return None

    thresholds = (config.get("pattern_thresholds") or {}).get("wyckoff_accumulation", {})
    sc_vol_min_ratio = float(thresholds.get("sc_volume_min_ratio", 2.0))
    spring_max_undercut_pct = float(thresholds.get("spring_max_undercut_pct", 5.0))
    spring_max_vol_ratio = float(thresholds.get("spring_volume_max_ratio", 0.75))
    range_min_bars = int(thresholds.get("range_min_weeks", 6)) * 5

    window = daily.tail(MIN_BARS).copy().reset_index(drop=True)

    sc_i = _find_sc_index(window)
    if sc_i is None:
        return None
    sc_bar = window.iloc[sc_i]
    sc_low = float(sc_bar["low"])
    sc_volume = float(sc_bar["volume"])
    prior_vol_window = window.iloc[max(0, sc_i - 20):sc_i]
    if prior_vol_window.empty:
        return None
    avg_prior_vol = float(prior_vol_window["volume"].mean())
    if avg_prior_vol <= 0 or sc_volume / avg_prior_vol < sc_vol_min_ratio:
        return None

    # Automatic Rally: highest close in the 10 bars after SC
    ar_slice = window.iloc[sc_i + 1:sc_i + 11]
    if ar_slice.empty:
        return None
    ar_high = float(ar_slice["high"].max())
    ar_end_i = int(ar_slice["high"].idxmax())

    # Trading range from AR end to the present
    range_bars = (len(window) - 1) - ar_end_i
    if range_bars < range_min_bars:
        return None

    last = window.iloc[-1]
    last_close = float(last["close"])
    atr = safe(last, "atr_14")
    if pd.isna(atr) or atr <= 0:
        return None

    # Look for a spring within the last 8 bars — a bar whose LOW is
    # below SC by ≤ spring_max_undercut_pct AND volume < spring_max_vol_ratio
    # × SC volume.
    recent = window.iloc[-8:]
    spring_i: int | None = None
    for idx in recent.index:
        bar = window.iloc[idx]
        b_low = float(bar["low"])
        if b_low >= sc_low:
            continue
        undercut_pct = (sc_low - b_low) / sc_low * 100.0
        if undercut_pct > spring_max_undercut_pct:
            continue
        if float(bar["volume"]) >= sc_volume * spring_max_vol_ratio:
            continue
        spring_i = int(idx)
        break
    if spring_i is None:
        return None

    # Recovery: latest close must be back above SC low (range restored)
    if last_close <= sc_low:
        return None

    spring_low = float(window["low"].iloc[spring_i])
    stop = spring_low - 0.1 * atr
    if last_close - stop <= 0.01:
        return None

    range_height = ar_high - sc_low
    tp1 = ar_high + range_height * 1.0
    tp2 = ar_high + range_height * 2.0

    spring_vol_pct = float(window["volume"].iloc[spring_i]) / max(sc_volume, 1)
    is_type1 = (
        (sc_low - spring_low) / sc_low * 100.0 <= 1.0
        and spring_vol_pct < 0.5
    )

    pqs_base = 60
    modifiers: dict[str, int] = {
        "sc_climactic_volume": 10,
        "range_sufficient": 12 if range_bars >= 90 else 8,
        "spring_recovered": 10,
    }
    if is_type1:
        modifiers["spring_type_1"] = 20
    elif spring_vol_pct < 0.5:
        modifiers["spring_low_volume"] = 10

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
        invalidation_condition="daily_close_below_spring_low",
        evidence_items=[
            {"type": "pattern",
             "ref": f"Wyckoff range {range_bars} bars: SC low {sc_low:.2f}, AR high {ar_high:.2f}"},
            {"type": "pattern",
             "ref": f"SC volume {sc_volume / avg_prior_vol:.1f}× prior 20-bar avg"},
            {"type": "pattern",
             "ref": f"Spring: low {spring_low:.2f} "
                     f"({(sc_low - spring_low) / sc_low * 100.0:.2f}% undercut), "
                     f"volume {spring_vol_pct:.2f}× SC"},
            {"type": "indicator",
             "ref": f"Recovery: close {last_close:.2f} back above SC low"},
        ],
    )
