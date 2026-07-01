"""MACD-run — trend-pullback momentum entry, winners run on a MACD cross-down exit.

Video-mined (rf_EQvubKlk), backtested: OOS PF ~1.52, +0.27R, and only ~0.26 correlated
with Momentum Breakout → a daily diversifier (see strategies/STRATEGY_GRID.md). The
author's "86% win rate" is false (~37% real); the edge is letting winners run, NOT a
fixed 1.5R target. Exit = MACD line crossing back below signal (handled by replay/exec
trail); the plan still carries a wide R target for the risk gate.

Pure function of (daily, hourly, config, as_of_ts, macro_context) → PatternResult.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from agents.detectors._helpers import apply_universal_modifiers, cap_pqs, safe, slice_as_of
from models.pattern import PatternResult

PATTERN_NAME = "macd_run"


def _macd(close: np.ndarray, fast: int, slow: int, sig: int):
    c = pd.Series(close)
    macd = c.ewm(span=fast, adjust=False).mean() - c.ewm(span=slow, adjust=False).mean()
    signal = macd.ewm(span=sig, adjust=False).mean()
    return macd.values, signal.values


def detect_macd_run(daily, hourly, config, as_of_ts, macro_context=None):
    th = (config.get("pattern_thresholds") or {}).get(PATTERN_NAME, {})
    fast = int(th.get("macd_fast", 12)); slow = int(th.get("macd_slow", 26)); sigp = int(th.get("macd_signal", 9))
    stop_atr_mult = float(th.get("stop_atr_mult", 1.5))
    tp1_r = float(th.get("tp1_r_multiple", 3.0)); tp2_r = float(th.get("tp2_r_multiple", 6.0))
    require_below_zero = bool(th.get("require_below_zero", True))
    require_trend = bool(th.get("require_trend", True))

    df = slice_as_of(daily, as_of_ts)
    if df is None or len(df) < 210:
        return None
    c = df["close"].values.astype(float)
    last = df.iloc[-1]
    close = float(c[-1]); atr = safe(last, "atr_14")
    if pd.isna(atr) or atr <= 0:
        return None

    macd, signal = _macd(c, fast, slow, sigp)
    cross_up = macd[-1] > signal[-1] and macd[-2] <= signal[-2]
    if not cross_up:
        return None
    if require_below_zero and not (macd[-1] < 0):
        return None

    sma200 = safe(last, "sma_200")
    if pd.isna(sma200) or sma200 <= 0:
        sma200 = float(pd.Series(c).rolling(200).mean().values[-1]) if len(c) >= 200 else float("nan")
    above_200 = (not pd.isna(sma200)) and close > sma200
    if require_trend and not above_200:
        return None

    entry_price = close
    stop_price = entry_price - stop_atr_mult * atr
    risk = entry_price - stop_price
    if risk <= 0.01:
        return None
    tp1 = entry_price + tp1_r * risk
    tp2 = entry_price + tp2_r * risk

    pqs_base = 60
    modifiers: dict[str, int] = {}
    depth = abs(macd[-1]) / atr if atr > 0 else 0.0     # deeper-below-zero cross = stronger snap
    modifiers["below_zero_cross"] = 10 if (macd[-1] < 0 and depth >= 0.2) else 5
    spy_above = (macro_context or {}).get("spy_above_sma200")
    if spy_above is True:
        modifiers["regime"] = 6
    elif spy_above is False:
        modifiers["regime"] = -8
    apply_universal_modifiers(modifiers, row=last, direction="long", macro_context=macro_context)
    pqs_total = cap_pqs(pqs_base, modifiers)

    return PatternResult(
        pattern_name=PATTERN_NAME, direction="long",
        pqs_base=pqs_base, pqs_modifiers=modifiers, pqs_total=pqs_total,
        entry_price=round(entry_price, 2), stop_price=round(stop_price, 2),
        tp1_price=round(tp1, 2), tp2_price=round(tp2, 2),
        invalidation_level=round(stop_price, 2),
        invalidation_condition="macd_cross_below_signal_or_initial_stop",
        evidence_items=[
            {"type": "pattern", "ref": f"MACD({fast},{slow},{sigp}) cross up below zero (macd {macd[-1]:.3f} > sig {signal[-1]:.3f})"},
            {"type": "filter", "ref": f"Trend gate: close {'>' if above_200 else '<='} SMA200 {sma200:.2f}"},
            {"type": "management", "ref": f"stop {stop_price:.2f} (entry-{stop_atr_mult:.1f}xATR); EXIT on MACD cross-down (let winners run)"},
            {"type": "note", "ref": "Author 'high win rate' claim is false (~37%); edge is the run-exit, not a fixed target."},
        ],
    )
