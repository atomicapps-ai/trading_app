"""Coil-Contraction Breakout — volatility-contraction (coil) then expansion breakout.

Video-mined (YWBLKRLnrZ0), backtested on 45 daily stocks: OOS PF 2.13, 55% win,
+0.42R, and only ~0.14 correlated with Momentum Breakout (a near-uncorrelated,
high-PF diversifier — the strongest new find of the web-strategy farm).

Edge = the CONTRACTION precondition (ATR10 < ATR50) makes it selective; the
breakout is confirmed by an expansion bar (TR > 1.5x median TR) on volume.

Pure function of (daily, hourly, config, as_of_ts, macro_context) → PatternResult,
matching the ALL_DETECTORS swing contract.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from agents.detectors._helpers import apply_universal_modifiers, cap_pqs, safe, slice_as_of
from models.pattern import PatternResult

PATTERN_NAME = "coil_breakout"


def _atr(h, l, c, n):
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return tr, pd.Series(tr).rolling(n).mean().values


def detect_coil_breakout(daily, hourly, config, as_of_ts, macro_context=None):
    th = (config.get("pattern_thresholds") or {}).get(PATTERN_NAME, {})
    rlb = int(th.get("range_lookback", 30))
    atr_fast = int(th.get("atr_fast", 10))
    atr_slow = int(th.get("atr_slow", 50))
    tr_mult = float(th.get("breakout_tr_mult", 1.5))
    vol_min = float(th.get("breakout_volume_min", 1.5))
    require_vol = bool(th.get("require_breakout_volume", True))
    require_coil = bool(th.get("require_coil", True))
    require_trend = bool(th.get("require_trend", True))
    tp1_r = float(th.get("tp1_r_multiple", 3.0))
    tp2_r = float(th.get("tp2_r_multiple", 6.0))

    df = slice_as_of(daily, as_of_ts)
    if df is None or len(df) < max(atr_slow, rlb) + 5:
        return None
    h = df["high"].values.astype(float); l = df["low"].values.astype(float)
    c = df["close"].values.astype(float); v = df["volume"].values.astype(float)
    last = df.iloc[-1]
    close = float(c[-1])

    # --- channel: prior N-day high/low (exclude current bar) ---
    prior_high = float(np.max(h[-(rlb + 1):-1]))
    range_low = float(np.min(l[-(rlb + 1):-1]))
    if close <= prior_high:
        return None

    # --- coil precondition: recent vol (ATR fast) < structural vol (ATR slow) ---
    tr, atr_f = _atr(h, l, c, atr_fast)
    _, atr_s = _atr(h, l, c, atr_slow)
    af = float(atr_f[-1]); as_ = float(atr_s[-1])
    if pd.isna(af) or pd.isna(as_) or as_ <= 0:
        return None
    coil = af < as_
    if require_coil and not coil:
        return None

    # --- expansion bar: today's TR > tr_mult x median TR(rlb) ---
    med_tr = float(pd.Series(tr).rolling(rlb).median().shift(1).values[-1])
    today_tr = float(tr[-1])
    if pd.isna(med_tr) or med_tr <= 0 or today_tr <= tr_mult * med_tr:
        return None

    # --- volume confirmation ---
    vavg = float(pd.Series(v).rolling(rlb).mean().values[-1])
    vol_ratio = (v[-1] / vavg) if vavg > 0 else float("nan")
    if require_vol and (pd.isna(vol_ratio) or vol_ratio < vol_min):
        return None

    # --- trend gate: close > SMA200 ---
    sma200 = safe(last, "sma_200")
    if pd.isna(sma200) or sma200 <= 0:
        sma200 = float(pd.Series(c).rolling(200).mean().values[-1]) if len(c) >= 200 else float("nan")
    above_200 = (not pd.isna(sma200)) and close > sma200
    if require_trend and not above_200:
        return None

    entry_price = close
    stop_price = range_low
    risk = entry_price - stop_price
    if risk <= 0.01:
        return None
    tp1 = entry_price + tp1_r * risk
    tp2 = entry_price + tp2_r * risk

    # --- PQS ---
    coil_ratio = af / as_ if as_ > 0 else 1.0
    pqs_base = 60
    modifiers: dict[str, int] = {}
    modifiers["coil_tightness"] = 14 if coil_ratio <= 0.7 else (8 if coil_ratio < 1.0 else 0)
    expansion = today_tr / med_tr if med_tr > 0 else 0.0
    modifiers["expansion_thrust"] = 10 if expansion >= 2.0 else 6
    if not pd.isna(vol_ratio):
        modifiers["breakout_volume"] = 15 if vol_ratio >= 2.0 else (10 if vol_ratio >= vol_min else 0)
    spy_above = (macro_context or {}).get("spy_above_sma200")
    if spy_above is True:
        modifiers["regime"] = 6
    elif spy_above is False:
        modifiers["regime"] = -8
    apply_universal_modifiers(modifiers, row=last, direction="long", macro_context=macro_context)
    pqs_total = cap_pqs(pqs_base, modifiers)

    vr_txt = "n/a" if pd.isna(vol_ratio) else f"{vol_ratio:.1f}x"
    return PatternResult(
        pattern_name=PATTERN_NAME, direction="long",
        pqs_base=pqs_base, pqs_modifiers=modifiers, pqs_total=pqs_total,
        entry_price=round(entry_price, 2), stop_price=round(stop_price, 2),
        tp1_price=round(tp1, 2), tp2_price=round(tp2, 2),
        invalidation_level=round(stop_price, 2),
        invalidation_condition="close_below_range_low",
        evidence_items=[
            {"type": "pattern", "ref": f"{rlb}-day coil breakout: close {close:.2f} > range high {prior_high:.2f} (range low {range_low:.2f})"},
            {"type": "filter", "ref": f"Coil contraction: ATR{atr_fast} {af:.2f} < ATR{atr_slow} {as_:.2f} (ratio {coil_ratio:.2f})"},
            {"type": "filter", "ref": f"Expansion bar: today TR {today_tr:.2f} = {expansion:.1f}x median TR{rlb} (need >{tr_mult:g}x)"},
            {"type": "filter", "ref": f"Breakout volume {vr_txt} {rlb}-day avg (need >={vol_min:g}x)"},
            {"type": "filter", "ref": f"Trend gate: close {'>' if above_200 else '<='} SMA200 {sma200:.2f}"},
            {"type": "management", "ref": f"stop {stop_price:.2f} (range low); targets {tp1_r:g}R / {tp2_r:g}R; let runners extend"},
        ],
    )
