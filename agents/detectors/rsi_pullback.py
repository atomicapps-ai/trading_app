"""RSI Pullback — Larry Connors short-term mean reversion (video W8ENIXvcGlQ).

Buy a shallow oversold dip inside an established uptrend, exit on the first RSI recovery.
Validated on the daily US-stock universe (OOS PF ~1.26-1.31, +0.10R, ~68% win) and gated as
a DIVERSIFIER — only 0.40 correlated with the live Fear-Dip Reversion (different trigger:
RSI(10)<30 with an RSI-recovery exit, no deep-ATR stretch). See strategies/strategy_docs/
RSI_PULLBACK.md and strategies/STRATEGY_GRID.md.

Rules:
  * Trend filter: close > SMA200 (uptrend only).
  * Entry: RSI(10) < 30 (shallow oversold) -> buy next open.
  * Exit (handled in replay/executioner): RSI(10) crosses back above 40, OR a 10-bar time stop.
  * Protective (disaster) stop only: entry - stop_atr_mult*ATR14. There is no fixed target;
    the edge is the fast RSI-recovery exit, not a TP.

Pure function of (daily, hourly, config, as_of_ts, macro_context) -> PatternResult.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from agents.detectors._helpers import apply_universal_modifiers, cap_pqs, safe, slice_as_of
from models.pattern import PatternResult

PATTERN_NAME = "rsi_pullback"


def _rsi(close: np.ndarray, n: int) -> np.ndarray:
    d = pd.Series(close).diff()
    up = d.clip(lower=0).ewm(alpha=1.0 / n, adjust=False).mean()
    dn = (-d).clip(lower=0).ewm(alpha=1.0 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).fillna(50).values


def detect_rsi_pullback(daily, hourly, config, as_of_ts, macro_context=None):
    th = (config.get("pattern_thresholds") or {}).get(PATTERN_NAME, {})
    rsi_len = int(th.get("rsi_length", 10))
    rsi_entry = float(th.get("rsi_entry", 30.0))
    stop_atr_mult = float(th.get("stop_atr_mult", 3.0))
    require_trend = bool(th.get("require_trend", True))

    df = slice_as_of(daily, as_of_ts)
    if df is None or len(df) < 210:
        return None
    c = df["close"].values.astype(float)
    last = df.iloc[-1]
    close = float(c[-1])
    atr = safe(last, "atr_14")
    if pd.isna(atr) or atr <= 0:
        return None

    sma200 = safe(last, "sma_200")
    if pd.isna(sma200) or sma200 <= 0:
        return None
    above_200 = close > sma200
    if require_trend and not above_200:
        return None

    rsi10 = _rsi(c, rsi_len)
    if not (rsi10[-1] < rsi_entry):
        return None

    entry_price = close
    stop_price = entry_price - stop_atr_mult * atr
    risk = entry_price - stop_price
    if risk <= 0.01:
        return None
    # No fixed target; carry a wide nominal R for the risk gate (exit is RSI-recovery/time).
    tp1 = entry_price + 1.0 * risk
    tp2 = entry_price + 2.0 * risk

    pqs_base = 58
    modifiers: dict[str, int] = {}
    if rsi10[-1] <= 20:
        modifiers["deep_oversold"] = 10
    elif rsi10[-1] <= 25:
        modifiers["oversold"] = 6
    dist200 = (close / sma200 - 1) * 100 if sma200 > 0 else 0.0
    if 0 < dist200 <= 15:
        modifiers["healthy_uptrend"] = 6      # dip in a trend, not overextended
    spy_above = (macro_context or {}).get("spy_above_sma200")
    if spy_above is True:
        modifiers["regime"] = 5
    elif spy_above is False:
        modifiers["regime"] = -6
    apply_universal_modifiers(modifiers, row=last, direction="long", macro_context=macro_context)
    pqs_total = cap_pqs(pqs_base, modifiers)

    return PatternResult(
        pattern_name=PATTERN_NAME, direction="long",
        pqs_base=pqs_base, pqs_modifiers=modifiers, pqs_total=pqs_total,
        entry_price=round(entry_price, 2), stop_price=round(stop_price, 2),
        tp1_price=round(tp1, 2), tp2_price=round(tp2, 2),
        invalidation_level=round(stop_price, 2),
        invalidation_condition="rsi10_recovers_above_40_or_time_stop_or_disaster_stop",
        evidence_items=[
            {"type": "pattern", "ref": f"RSI({rsi_len}) {rsi10[-1]:.1f} < {rsi_entry:.0f} — shallow oversold pullback"},
            {"type": "filter", "ref": f"Trend gate: close {close:.2f} > SMA200 {sma200:.2f} (dist {dist200:+.0f}%)"},
            {"type": "management", "ref": f"EXIT on RSI({rsi_len})>40 or 10-bar time stop; disaster stop {stop_price:.2f} (entry-{stop_atr_mult:.1f}xATR)"},
            {"type": "note", "ref": "Connors pullback (W8ENIXvcGlQ); edge is the fast RSI-recovery exit, high win rate / small avg win. Diversifier vs Fear-Dip (corr 0.40)."},
        ],
    )
