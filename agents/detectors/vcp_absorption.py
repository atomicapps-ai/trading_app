"""VCP — Absorption at Resistance detector.

Translation of the Pine Script "VCP — Absorption at Resistance v2"
(prototyped in TradingView) into the project's pure-function detector
style. Detects the specific Minervini variant where a flat horizontal
resistance is repeatedly tested while pullback lows step up — a
"shrinking wedge into an apex" with volume drying up.

Narrative (full version in docs/indicators/vcp_absorption.md):
    A sustained move up establishes a resistance level. Sellers defend
    that ceiling repeatedly while buyers absorb the supply, with each
    rally attempt producing a shallower pullback than the last and a
    higher low than the last. Volume dries up. Eventually supply is
    exhausted and price breaks out on volume expansion.

Pure function of (daily, hourly, config, as_of_ts). The hourly arg is
ignored — this pattern lives on the daily timeframe. ``as_of_ts``
support means the detector replays identically on any historical bar,
which is what Phase 5 backtesting needs.

Pipeline (matches docs/indicators/vcp_absorption.md §3):
    1. Context filter — recent strength rally OR Minervini Stage 2
    2. Pivot extraction (N-bar fractals via _helpers)
    3. Resistance level = max of pivot highs in the recent base
    4. Touch counting at the resistance (within X * ATR tolerance)
    5. Contraction depths from each touching pivot high to next pivot low
    6. Overall compression test (final depth <= compressionMax * first depth)
    7. Higher-lows test on the pullback sequence
    8. Volume dry-up test
    9. Base-length window check
   10. Output PatternResult with entry / stop / TP levels + diagnostic dict
"""
from __future__ import annotations

import math

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

PATTERN_NAME = "vcp_absorption"


# --------------------------------------------------------------------------- #
# Default thresholds — match Pine v2 defaults; override via config
# --------------------------------------------------------------------------- #

DEFAULTS: dict = {
    # Context
    "use_stage2":         False,   # Minervini Trend Template (off by default — absorption forms before MAs stack)
    "use_strength":       True,    # post-rally / pre-breakout context
    "strength_bars":      60,
    "min_rally":          0.15,    # 15% rally in strength_bars
    "pullback_ceiling":   0.15,    # current price within 15% of lookback high

    # Pivots
    "pivot_width":        5,       # N-bar fractal (left=right=N)
    "pivot_lookback":     15,      # how many recent pivots to retain

    # Absorption structure
    "min_touches":        3,
    "cluster_atr":        1.5,     # touches within 1.5 * ATR of resistance
                                   # (was 0.7; SMCI calibration showed real
                                   # absorption highs scatter ~1-2 ATR around
                                   # the resistance, not pixel-perfect)

    # Tightening
    "min_t":              3,       # minimum number of contractions
    "compression_max":    0.5,     # final depth <= compression_max * first depth
    "max_final_depth":    0.18,    # final contraction <= 18%
                                   # (was 0.12; bumped because the SHAKEOUT bar
                                   # often deepens the final low temporarily.
                                   # 18% caps it without rejecting true setups)
    # Higher lows: tolerate up to N violations to allow a shakeout/spring,
    # which by definition takes out a prior low to trigger weak-hand stops.
    "max_lowerlow_violations": 1,

    # Volume — base-period dry-up vs pre-base average. Replaces the
    # old "SMA(10)/SMA(50) at latest bar" which was poisoned by a
    # single high-volume day (e.g. the shakeout on Jan 17 2024 SMCI).
    "use_vol_dryup":      True,
    "vol_base_window":    30,      # avg vol over last 30 bars of base
    "vol_pre_window":     60,      # vs avg vol over preceding 60 bars
    "vol_dryup_pct":      0.85,    # base-period vol <= 85% of pre-base

    # Base length (in bars; daily timeframe)
    "min_base_bars":      30,
    "max_base_bars":      250,

    # Strict-absorption guard — reject cups & wide bases.
    # The deepest LOW across the entire base window must be no more
    # than max_drawdown_pct below the resistance. AVGO 2022 had a
    # cup bottom 28.7% below resistance, so 0.25 correctly rejects
    # it; OLECTRA's first depth was 21.6%, well within 25%.
    # The contraction-depth tests above only see adjacent pivot
    # pairs and miss deep drawdowns between non-adjacent touch
    # pivots, which is why this separate guard is needed.
    "max_drawdown_pct":   0.25,

    # Trade plan
    "stop_buffer_atr":    0.5,     # stop = lowest pivot low - buffer * ATR
    "tp1_atr_multiple":   3.0,     # TP1 = entry + 3 * ATR (≈ measured-move proxy)
    "tp2_atr_multiple":   6.0,
}


def _cfg(config: dict, key: str):
    """Look up a threshold from config['pattern_thresholds']['vcp_absorption']
    or fall back to DEFAULTS. Keeps the detector standalone-usable."""
    section = (config or {}).get("pattern_thresholds", {}).get(PATTERN_NAME, {})
    return section.get(key, DEFAULTS[key])


def detect_vcp_absorption(
    daily: pd.DataFrame,
    hourly: pd.DataFrame | None = None,
    config: dict | None = None,
    as_of_ts: pd.Timestamp | None = None,
    macro_context: dict | None = None,
) -> PatternResult | None:
    """Detect absorption-at-resistance VCP at the most recent bar of
    ``daily`` (sliced to ``as_of_ts``).

    Returns ``PatternResult`` on detection, ``None`` otherwise. The
    result's ``evidence_items`` carry the diagnostic dict so callers
    (and the smoke script) can see exactly what fired.
    """
    config = config or {}
    daily = slice_as_of(daily, as_of_ts)
    if len(daily) < 100:
        return None

    last = daily.iloc[-1]
    close = float(last["close"])
    atr = safe(last, "atr_14")
    if pd.isna(atr) or atr <= 0:
        return None

    # ── Step 1: context filters ──────────────────────────────────────
    ctx_ok, ctx_diag = _check_context(daily, last, config)
    if not ctx_ok:
        return None

    # ── Step 2: pivot extraction ─────────────────────────────────────
    pivot_w = _cfg(config, "pivot_width")
    ph_idx = swing_high_indices(daily["high"], left=pivot_w, right=pivot_w)
    pl_idx = swing_low_indices(daily["low"],  left=pivot_w, right=pivot_w)

    # Retain only the most recent N pivots for the absorption window.
    keep = _cfg(config, "pivot_lookback")
    ph_idx = ph_idx[-keep:]
    pl_idx = pl_idx[-keep:]
    if len(ph_idx) < _cfg(config, "min_touches") or not pl_idx:
        return None

    ph_vals = [float(daily["high"].iat[i]) for i in ph_idx]
    pl_vals = [float(daily["low"].iat[i])  for i in pl_idx]

    # ── Step 3: resistance level + touch count ───────────────────────
    resistance = max(ph_vals)
    tol = _cfg(config, "cluster_atr") * atr
    touch_count = sum(1 for v in ph_vals if abs(v - resistance) <= tol)
    if touch_count < _cfg(config, "min_touches"):
        return None

    # ── Step 4: build contractions ───────────────────────────────────
    # Pair each touching pivot high with the next pivot low that comes
    # before the subsequent pivot high. That defines one contraction.
    depths: list[float] = []
    paired_lows: list[float] = []
    paired_high_bars: list[int] = []

    for i, ph_bar in enumerate(ph_idx):
        ph_val = ph_vals[i]
        if abs(ph_val - resistance) > tol:
            continue
        next_ph_bar = ph_idx[i + 1] if i + 1 < len(ph_idx) else math.inf
        for j, pl_bar in enumerate(pl_idx):
            if pl_bar > ph_bar and pl_bar < next_ph_bar:
                pl_val = pl_vals[j]
                depth = (ph_val - pl_val) / ph_val
                depths.append(depth)
                paired_lows.append(pl_val)
                paired_high_bars.append(ph_bar)
                break

    nc = len(depths)
    min_t = _cfg(config, "min_t")
    if nc < min_t:
        return None

    first_depth = depths[0]
    final_depth = depths[-1]
    compression = final_depth / first_depth if first_depth > 0 else math.inf

    # ── Step 5: tightening (overall compression) ─────────────────────
    if compression > _cfg(config, "compression_max"):
        return None
    if final_depth > _cfg(config, "max_final_depth"):
        return None

    # ── Step 6: higher lows (tolerates shakeout) ─────────────────────
    # The shakeout/spring near the apex deliberately takes out the
    # prior pivot low to flush weak hands. So we allow up to
    # max_lowerlow_violations across the contraction sequence.
    max_violations = _cfg(config, "max_lowerlow_violations")
    if max_violations >= 0 and len(paired_lows) >= 2:
        violations = sum(
            1 for k in range(1, len(paired_lows))
            if paired_lows[k] <= paired_lows[k - 1]
        )
        if violations > max_violations:
            return None

    # ── Step 7: volume dry-up vs pre-base ────────────────────────────
    # Compare avg volume over the last vol_base_window bars (the
    # tightening portion of the base) to avg volume over the
    # preceding vol_pre_window bars (the run-up + early base). This
    # is robust to single high-volume days that would poison a
    # SMA(10)/SMA(50) ratio at the latest bar.
    vol_ratio = math.nan
    if _cfg(config, "use_vol_dryup"):
        vbw = int(_cfg(config, "vol_base_window"))
        vpw = int(_cfg(config, "vol_pre_window"))
        if len(daily) >= vbw + vpw:
            base_vol = daily["volume"].iloc[-vbw:].mean()
            pre_vol  = daily["volume"].iloc[-(vbw + vpw):-vbw].mean()
            if pre_vol > 0:
                vol_ratio = base_vol / pre_vol
        if pd.isna(vol_ratio) or vol_ratio > _cfg(config, "vol_dryup_pct"):
            return None

    # ── Step 8: base length ──────────────────────────────────────────
    base_start_bar = paired_high_bars[0]
    base_len = (len(daily) - 1) - base_start_bar
    if not (_cfg(config, "min_base_bars") <= base_len <= _cfg(config, "max_base_bars")):
        return None

    # ── Step 8b: strict-absorption guard — reject cups & wide bases ──
    # The contraction tests only see adjacent pivot pairs. A cup with
    # a deep mid-base bottom between non-adjacent touch pivots passes
    # those tests but is NOT absorption. This guard catches it by
    # looking at the actual lowest LOW across the entire base window.
    base_window_low = float(daily["low"].iloc[base_start_bar:].min())
    drawdown = (resistance - base_window_low) / resistance
    if drawdown > _cfg(config, "max_drawdown_pct"):
        return None

    # ── Step 9: build trade plan ─────────────────────────────────────
    entry = resistance + 0.01  # break-of-resistance entry
    stop_low = min(paired_lows)
    stop = stop_low - _cfg(config, "stop_buffer_atr") * atr
    tp1 = entry + _cfg(config, "tp1_atr_multiple") * atr
    tp2 = entry + _cfg(config, "tp2_atr_multiple") * atr
    if abs(entry - stop) < 0.01:
        return None

    # ── Step 10: PQS scoring ─────────────────────────────────────────
    pqs_base = 60
    modifiers: dict[str, int] = {
        "compression_quality": int(round((1 - compression) * 20)),
        "touch_count_bonus":   min(10, (touch_count - 3) * 3),
        "tight_final": 8 if final_depth <= 0.07 else (4 if final_depth <= 0.10 else 0),
    }
    if not pd.isna(vol_ratio):
        if vol_ratio <= 0.40:
            modifiers["volume_dryup_strong"] = 10
        elif vol_ratio <= 0.55:
            modifiers["volume_dryup"] = 6
    apply_universal_modifiers(
        modifiers, row=last, direction="long", macro_context=macro_context,
    )
    pqs_total = cap_pqs(pqs_base, modifiers)

    # ── Diagnostic payload — keep raw numbers in evidence ────────────
    diag = {
        "resistance":      round(resistance, 4),
        "touch_count":     touch_count,
        "contractions":    nc,
        "first_depth_pct": round(first_depth * 100, 2),
        "final_depth_pct": round(final_depth * 100, 2),
        "compression":     round(compression, 3),
        "vol_ratio":       None if pd.isna(vol_ratio) else round(vol_ratio, 3),
        "base_bars":       base_len,
        "drawdown_pct":    round(drawdown * 100, 2),
        "deepest_low":     round(base_window_low, 4),
        "depths_pct":      [round(d * 100, 2) for d in depths],
        "paired_lows":     [round(v, 4) for v in paired_lows],
        "context":         ctx_diag,
    }

    evidence = [
        {"type": "pattern", "ref": (
            f"resistance ${resistance:.2f}, {touch_count} touches"
        )},
        {"type": "pattern", "ref": (
            f"contractions {[round(d*100,1) for d in depths]} % "
            f"(compression {compression:.2f}, final {final_depth*100:.1f}%)"
        )},
        {"type": "pattern", "ref": (
            f"base {base_len} bars, vol ratio "
            f"{'n/a' if pd.isna(vol_ratio) else f'{vol_ratio:.2f}'}"
        )},
        {"type": "diagnostic", "ref": diag},
    ]

    return PatternResult(
        pattern_name=PATTERN_NAME,
        direction="long",
        pqs_base=pqs_base,
        pqs_modifiers=modifiers,
        pqs_total=pqs_total,
        entry_price=round(entry, 2),
        stop_price=round(stop, 2),
        tp1_price=round(tp1, 2),
        tp2_price=round(tp2, 2),
        invalidation_level=round(stop, 2),
        invalidation_condition="daily_close_below_stop",
        evidence_items=evidence,
    )


# --------------------------------------------------------------------------- #
# Context filter
# --------------------------------------------------------------------------- #


def _check_context(
    daily: pd.DataFrame, last: pd.Series, config: dict,
) -> tuple[bool, dict]:
    """Returns (passed, diag_dict). At least one of stage2 / strength
    must be enabled and pass; if both are disabled, context is open."""
    diag: dict = {}
    use_stage2 = _cfg(config, "use_stage2")
    use_strength = _cfg(config, "use_strength")

    stage2_ok = True
    if use_stage2:
        close = float(last["close"])
        sma50 = safe(last, "sma_50")
        sma150 = float(daily["close"].rolling(150, min_periods=150).mean().iat[-1])
        sma200 = safe(last, "sma_200")
        sma200_1m = float(daily["close"].rolling(200, min_periods=200).mean().iat[-22]) if len(daily) >= 222 else float("nan")
        high52 = float(daily["high"].rolling(252, min_periods=252).max().iat[-1])
        low52  = float(daily["low"].rolling(252, min_periods=252).min().iat[-1])
        stage2_ok = (
            not pd.isna(sma50) and not pd.isna(sma200) and not pd.isna(sma200_1m) and
            close > sma50 > sma150 > sma200 and
            sma200 > sma200_1m and
            close >= high52 * 0.75 and
            close >= low52 * 1.25
        )
        diag["stage2_ok"] = stage2_ok

    strength_ok = True
    if use_strength:
        n = _cfg(config, "strength_bars")
        if len(daily) < n:
            return False, {"strength_ok": False, "reason": "insufficient_history"}
        window = daily["close"].iloc[-n:]
        hi = float(window.max())
        lo = float(window.min())
        rally = (hi - lo) / lo if lo > 0 else 0.0
        close = float(last["close"])
        within_top = close >= hi * (1 - _cfg(config, "pullback_ceiling"))
        strength_ok = rally >= _cfg(config, "min_rally") and within_top
        diag["rally"] = round(rally, 3)
        diag["within_top"] = within_top
        diag["strength_ok"] = strength_ok

    if not use_stage2 and not use_strength:
        return True, {"open": True}
    return (stage2_ok and strength_ok), diag
