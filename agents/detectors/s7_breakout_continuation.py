"""S7 — Multi-Month Breakout Continuation (volume + ADX + trend-zone filters)."""
from __future__ import annotations
import numpy as np
import pandas as pd
from agents.detectors._helpers import apply_universal_modifiers, cap_pqs, safe, slice_as_of
from models.pattern import PatternResult

PATTERN_NAME = "s7_breakout_continuation"


def _adx(df, n=14):
    h = df["high"].values; l = df["low"].values; c = df["close"].values
    if len(c) < n * 2:
        return float("nan")
    up = np.diff(h, prepend=h[0]); dn = -np.diff(l, prepend=l[0])
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    trn = pd.Series(tr).rolling(n).mean().values
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi = 100 * pd.Series(pdm).rolling(n).mean().values / trn
        ndi = 100 * pd.Series(ndm).rolling(n).mean().values / trn
        dx = 100 * np.abs(pdi - ndi) / (pdi + ndi + 1e-9)
    v = pd.Series(dx).rolling(n).mean().values
    return float(v[-1]) if len(v) and v[-1] == v[-1] else float("nan")


def detect_s7_breakout_continuation(daily, hourly, config, as_of_ts, macro_context=None):
    th = (config.get("pattern_thresholds") or {}).get(PATTERN_NAME, {})
    lookback = int(th.get("lookback_high", 126))
    stop_atr_mult = float(th.get("stop_atr_mult", 1.0))
    tp1_r = float(th.get("tp1_r_multiple", 3.0))
    tp2_r = float(th.get("tp2_r_multiple", 6.0))

    df = slice_as_of(daily, as_of_ts)
    if df is None or len(df) < lookback + 5:
        return None
    last = df.iloc[-1]
    close = float(last["close"]); atr = safe(last, "atr_14")
    if pd.isna(atr) or atr <= 0:
        return None
    prior_high = float(df["high"].iloc[-(lookback + 1):-1].max())
    if close <= prior_high:
        return None
    entry_price = close
    stop_price = entry_price - stop_atr_mult * atr
    risk = entry_price - stop_price
    if risk <= 0.01:
        return None
    tp1 = entry_price + tp1_r * risk
    tp2 = entry_price + tp2_r * risk

    # --- Breakout VOLUME filter (vol>=1.5x ~2x expectancy) ---
    require_vol = bool(th.get("require_breakout_volume", True))
    vol_min = float(th.get("breakout_volume_min", 1.5))
    vol_ratio = safe(last, "volume_ratio")
    if require_vol and (pd.isna(vol_ratio) or vol_ratio < vol_min):
        return None
    if pd.isna(vol_ratio): vol_strength, vol_pts = "UNCONFIRMED", 0
    elif vol_ratio >= 2.0: vol_strength, vol_pts = "STRONG", 15
    elif vol_ratio >= vol_min: vol_strength, vol_pts = "MODERATE", 10
    else: vol_strength, vol_pts = "WEAK", 0

    # --- ADX trend-strength filter (skip chop; ADX<20 was PF ~1.1) ---
    adx_min = float(th.get("require_min_adx", 20.0))
    adx = _adx(df)
    if adx_min > 0 and (pd.isna(adx) or adx < adx_min):
        return None
    if pd.isna(adx): adx_strength, adx_pts = "n/a", 0
    elif adx >= 30: adx_strength, adx_pts = "STRONG", 8
    elif adx >= 20: adx_strength, adx_pts = "MODERATE", 5
    else: adx_strength, adx_pts = "WEAK", 0

    # --- Distance-from-200MA trend zone (5-15% above = sweet spot, PF 2.34) ---
    zlo = float(th.get("trend_zone_lo", 0.05)); zhi = float(th.get("trend_zone_hi", 0.15))
    require_zone = bool(th.get("require_trend_zone", False))
    sma200 = safe(last, "sma_200")
    dist = (close - sma200) / sma200 if (not pd.isna(sma200) and sma200 > 0) else float("nan")
    in_zone = (not pd.isna(dist)) and (zlo <= dist <= zhi)
    if require_zone and not in_zone:
        return None
    if in_zone: zone_strength, zone_pts = "SWEET-SPOT", 12
    elif (not pd.isna(dist)) and dist > zhi: zone_strength, zone_pts = "EXTENDED", 0
    elif (not pd.isna(dist)) and dist < zlo: zone_strength, zone_pts = "EARLY", 4
    else: zone_strength, zone_pts = "n/a", 0

    spy_above = (macro_context or {}).get("spy_above_sma200")
    if spy_above is True: regime_strength, regime_pts = "SUPPORTIVE (SPY>200MA)", 6
    elif spy_above is False: regime_strength, regime_pts = "HEADWIND (SPY<200MA)", -8
    else: regime_strength, regime_pts = "unknown", 0

    pqs_base = 60
    modifiers = {}
    clearance = (close - prior_high) / atr
    modifiers["breakout_strength"] = 8 if clearance >= 0.5 else 4
    modifiers["breakout_volume"] = vol_pts
    if adx_pts: modifiers["adx_trend"] = adx_pts
    if zone_pts: modifiers["trend_zone"] = zone_pts
    if regime_pts: modifiers["regime"] = regime_pts
    if len(df) >= 253 and close > float(df["high"].iloc[-253:-1].max()):
        modifiers["new_52w_high"] = 6
    apply_universal_modifiers(modifiers, row=last, direction="long", macro_context=macro_context)
    pqs_total = cap_pqs(pqs_base, modifiers)

    vr_txt = "n/a" if pd.isna(vol_ratio) else f"{vol_ratio:.1f}x"
    adx_txt = "n/a" if pd.isna(adx) else f"{adx:.0f}"
    dist_txt = "n/a" if pd.isna(dist) else f"{dist*100:+.0f}%"
    return PatternResult(
        pattern_name=PATTERN_NAME, direction="long",
        pqs_base=pqs_base, pqs_modifiers=modifiers, pqs_total=pqs_total,
        entry_price=round(entry_price, 2), stop_price=round(stop_price, 2),
        tp1_price=round(tp1, 2), tp2_price=round(tp2, 2),
        invalidation_level=round(stop_price, 2),
        invalidation_condition="close_below_50d_sma_or_initial_stop",
        evidence_items=[
            {"type": "pattern", "ref": f"{lookback}-day high breakout: close {close:.2f} > prior high {prior_high:.2f}"},
            {"type": "filter", "ref": f"Breakout volume {vr_txt} 20-day avg - {vol_strength} support"},
            {"type": "filter", "ref": f"Trend strength ADX {adx_txt} - {adx_strength} (filter: skip ADX<{adx_min:g} chop)"},
            {"type": "filter", "ref": f"Distance from 200MA {dist_txt} - {zone_strength} (sweet spot {zlo*100:g}-{zhi*100:g}%)"},
            {"type": "filter", "ref": f"Market regime: {regime_strength}"},
            {"type": "indicator", "ref": f"clears prior high by {clearance:.2f}xATR (ATR14 {atr:.2f})"},
            {"type": "management", "ref": f"stop {stop_price:.2f} (entry-{stop_atr_mult:.1f}xATR); trail 50-day SMA; let winners run"},
        ],
    )
