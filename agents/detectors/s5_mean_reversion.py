"""S5 — Mean-Reversion to the 50-day MA (fear-regime + deep-fear + uptrend filters)."""
from __future__ import annotations
import pandas as pd
from agents.detectors._helpers import cap_pqs, safe, slice_as_of
from models.pattern import PatternResult

PATTERN_NAME = "s5_mean_reversion"


def detect_s5_mean_reversion(daily, hourly, config, as_of_ts, macro_context=None):
    th = (config.get("pattern_thresholds") or {}).get(PATTERN_NAME, {})
    stretch_mult = float(th.get("stretch_atr_mult", 3.0))
    stop_atr_mult = float(th.get("stop_atr_mult", 1.0))

    df = slice_as_of(daily, as_of_ts)
    if df is None or len(df) < 60:
        return None
    last = df.iloc[-1]
    close = float(last["close"]); atr = safe(last, "atr_14"); sma50 = safe(last, "sma_50")
    if pd.isna(atr) or atr <= 0 or pd.isna(sma50):
        return None
    stretch = (sma50 - close) / atr
    if stretch < stretch_mult:
        return None
    entry_price = close
    stop_price = entry_price - stop_atr_mult * atr
    risk = entry_price - stop_price
    if risk <= 0.01 or sma50 <= entry_price:
        return None
    tp2 = sma50
    tp1 = entry_price + max(0.7 * (sma50 - entry_price), 2.2 * risk)
    if tp1 >= tp2:
        tp1 = entry_price + 0.5 * (sma50 - entry_price)

    # --- FEAR-regime filter (+ deep-fear tier: VIX>=32 was win 46% / PF 3.13) ---
    require_fear = bool(th.get("require_fear_regime", True))
    fear_vix_min = float(th.get("fear_vix_min", 26.0))
    fear_vix_extreme = float(th.get("fear_vix_extreme", 32.0))
    spy_above = (macro_context or {}).get("spy_above_sma200")
    vix_level = (macro_context or {}).get("vix_level")
    spy_fear = spy_above is False
    vix_fear = isinstance(vix_level, (int, float)) and vix_level >= fear_vix_min
    extreme = isinstance(vix_level, (int, float)) and vix_level >= fear_vix_extreme
    fear_score = (1 if spy_fear else 0) + (1 if vix_fear else 0)
    macro_known = (spy_above is not None) or isinstance(vix_level, (int, float))
    if require_fear and macro_known and fear_score == 0:
        return None
    if extreme:
        fear_strength, fear_pts = "EXTREME", 16
    elif fear_score >= 2:
        fear_strength, fear_pts = "STRONG", 12
    elif fear_score == 1:
        fear_strength, fear_pts = "MODERATE", 7
    else:
        fear_strength, fear_pts = ("unknown" if not macro_known else "none"), 0

    # --- Uptrend-dip filter (buy the dip IN an uptrend, not a falling knife) ---
    sma200 = safe(last, "sma_200")
    uptrend_dip = (not pd.isna(sma200)) and close > sma200

    pqs_base = 55
    modifiers = {}
    if stretch >= 3.5:
        modifiers["deep_stretch"] = 10
    elif stretch >= 3.0:
        modifiers["stretch"] = 6
    if fear_pts:
        modifiers["fear_regime"] = fear_pts
    if uptrend_dip:
        modifiers["uptrend_dip"] = 8
    rsi = safe(last, "rsi_14")
    if not pd.isna(rsi) and rsi <= 25:
        modifiers["oversold_rsi"] = 6
    # NOTE: climax-volume bonus removed — attribution showed vol>=2x dips were
    # slightly WORSE, so rewarding them was counterproductive.
    pqs_total = cap_pqs(pqs_base, modifiers)
    vix_txt = f"{vix_level:.0f}" if isinstance(vix_level, (int, float)) else "n/a"
    dist200 = f"{(close/sma200-1)*100:+.0f}%" if (not pd.isna(sma200) and sma200 > 0) else "n/a"

    return PatternResult(
        pattern_name=PATTERN_NAME, direction="long",
        pqs_base=pqs_base, pqs_modifiers=modifiers, pqs_total=pqs_total,
        entry_price=round(entry_price, 2), stop_price=round(stop_price, 2),
        tp1_price=round(tp1, 2), tp2_price=round(tp2, 2),
        invalidation_level=round(stop_price, 2),
        invalidation_condition="close_below_initial_stop",
        evidence_items=[
            {"type": "pattern", "ref": f"stretched {stretch:.1f}xATR below SMA50 (close {close:.2f} vs SMA50 {sma50:.2f})"},
            {"type": "filter", "ref": f"Fear regime {fear_strength} (VIX {vix_txt}, SPY<200MA={spy_fear}) - deeper fear = stronger edge"},
            {"type": "filter", "ref": f"Trend: {'DIP-IN-UPTREND (close>200MA)' if uptrend_dip else 'below 200MA (weaker)'} - dist {dist200}"},
            {"type": "indicator", "ref": f"target = SMA50 {sma50:.2f}; stop {stop_price:.2f} (entry-{stop_atr_mult:.1f}xATR)"},
            {"type": "management", "ref": "mean-reversion; max hold ~45 bars"},
        ],
    )
