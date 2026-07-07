"""Hidden Divergence — RSI bullish hidden divergence, trend continuation (video 9KVvwJHvcyE).

In an uptrend (above the 200-EMA), price makes a HIGHER low while RSI makes a LOWER low — a
"hidden" divergence that signals continuation, not reversal. Confirmed with a stochastic filter
and ridden as a trend trade. Validated on daily US stocks (OOS PF ~1.21, +0.06R) and gated as
the cleanest DIVERSIFIER in the book (<=0.24 correlated with every live strategy). See
strategies/strategy_docs/HIDDEN_DIVERGENCE.md and STRATEGY_GRID.md.

Rules (long):
  * Trend filter: close > 200-EMA.
  * Two confirmed swing lows (fractal +-pivot_k): the more recent low is HIGHER than the prior
    (price higher-low) while RSI(14) at the recent low is LOWER than at the prior (RSI lower-low).
  * Stochastic %K(14,3) < stoch_max at the recent low (confirmation).
  * Fire on the bar the recent pivot is confirmed; enter next open; stop below the recent swing
    low; ride the trend (trailing exit) — no fixed target.

Pure function of (daily, hourly, config, as_of_ts, macro_context) -> PatternResult.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from agents.detectors._helpers import apply_universal_modifiers, cap_pqs, safe, slice_as_of
from models.pattern import PatternResult

PATTERN_NAME = "hidden_divergence"


def _stoch_k(df: pd.DataFrame, n: int = 14, k: int = 3) -> np.ndarray:
    hi = df["high"].rolling(n).max()
    lo = df["low"].rolling(n).min()
    raw = 100 * (df["close"] - lo) / (hi - lo).replace(0, np.nan)
    return raw.rolling(k).mean().fillna(50).values


def _is_pivot_low(low: np.ndarray, j: int, k: int) -> bool:
    if j - k < 0 or j + k >= len(low):
        return False
    return low[j] == low[j - k: j + k + 1].min()


def detect_hidden_divergence(daily, hourly, config, as_of_ts, macro_context=None):
    th = (config.get("pattern_thresholds") or {}).get(PATTERN_NAME, {})
    pivot_k = int(th.get("pivot_k", 3))
    max_gap = int(th.get("max_pivot_gap", 40))
    stoch_max = float(th.get("stoch_max", 45.0))
    stop_buffer_atr = float(th.get("stop_buffer_atr", 0.1))
    ema_len = int(th.get("trend_ema", 200))

    df = slice_as_of(daily, as_of_ts)
    if df is None or len(df) < 260:
        return None
    c = df["close"].values.astype(float)
    low = df["low"].values.astype(float)
    last = df.iloc[-1]
    close = float(c[-1])
    atr = safe(last, "atr_14")
    if pd.isna(atr) or atr <= 0:
        return None

    ema200 = pd.Series(c).ewm(span=ema_len, adjust=False).mean().values
    if not (close > ema200[-1]):
        return None

    rsi = df["rsi_14"].values if "rsi_14" in df.columns else None
    if rsi is None or np.isnan(rsi[-1]):
        return None
    stoch = _stoch_k(df)

    n = len(df)
    p2 = n - 1 - pivot_k          # recent pivot candidate (just confirmed this bar)
    if p2 < pivot_k + 1 or not _is_pivot_low(low, p2, pivot_k):
        return None
    # find the prior confirmed pivot low within max_gap bars before p2
    p1 = None
    for j in range(p2 - 1, max(p2 - max_gap, pivot_k) - 1, -1):
        if _is_pivot_low(low, j, pivot_k):
            p1 = j
            break
    if p1 is None:
        return None

    higher_low = low[p2] > low[p1]
    rsi_lower_low = rsi[p2] < rsi[p1]
    if not (higher_low and rsi_lower_low):
        return None
    if not (stoch[p2] < stoch_max):
        return None

    entry_price = close
    stop_price = float(low[p2]) - stop_buffer_atr * atr
    risk = entry_price - stop_price
    if risk <= 0.01:
        return None
    tp1 = entry_price + 1.5 * risk     # nominal for the risk gate; real exit is the trend trail
    tp2 = entry_price + 3.0 * risk

    pqs_base = 56
    modifiers: dict[str, int] = {}
    rsi_gap = float(rsi[p1] - rsi[p2])
    if rsi_gap >= 8:
        modifiers["strong_divergence"] = 10
    elif rsi_gap >= 3:
        modifiers["divergence"] = 6
    if stoch[p2] < 25:
        modifiers["deep_stoch"] = 5
    sma200 = safe(last, "sma_200")
    if not pd.isna(sma200) and sma200 > 0:
        dist = (close / sma200 - 1) * 100
        if 0 < dist <= 20:
            modifiers["healthy_uptrend"] = 6
    apply_universal_modifiers(modifiers, row=last, direction="long", macro_context=macro_context)
    pqs_total = cap_pqs(pqs_base, modifiers)

    return PatternResult(
        pattern_name=PATTERN_NAME, direction="long",
        pqs_base=pqs_base, pqs_modifiers=modifiers, pqs_total=pqs_total,
        entry_price=round(entry_price, 2), stop_price=round(stop_price, 2),
        tp1_price=round(tp1, 2), tp2_price=round(tp2, 2),
        invalidation_level=round(stop_price, 2),
        invalidation_condition="close_below_swing_stop_or_trend_trail",
        evidence_items=[
            {"type": "pattern", "ref": f"Bullish hidden divergence: price higher-low ({low[p1]:.2f}->{low[p2]:.2f}) vs RSI lower-low ({rsi[p1]:.0f}->{rsi[p2]:.0f})"},
            {"type": "filter", "ref": f"Trend: close {close:.2f} > 200-EMA {ema200[-1]:.2f}; Stoch %K {stoch[p2]:.0f} < {stoch_max:.0f}"},
            {"type": "management", "ref": f"stop {stop_price:.2f} (swing low - {stop_buffer_atr:.1f}xATR); RIDE the trend (trailing exit), no fixed target"},
            {"type": "note", "ref": "RSI hidden divergence (9KVvwJHvcyE). Cleanest diversifier: <=0.24 corr to the whole live book."},
        ],
    )
