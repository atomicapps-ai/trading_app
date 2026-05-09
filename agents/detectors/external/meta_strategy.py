"""meta_strategy.py — universal parameterized strategy.

A single ``detect()`` function whose behavior is controlled entirely by a
``config`` dict. The dict picks one entry primitive, any subset of regime
filters, optionally a volume filter, one stop type, and one TP type. The
random-search engine samples thousands of these configs to find what
actually works.

Same Signal/Trade contract as the other external detectors so the existing
``simulate_trades`` works unchanged.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from agents.detectors.external._base import Signal


META = {
    "slug": "meta_strategy",
    "family": "configurable",
    "natural_interval": "1d",
    "long_only": False,
    "primitives": [
        "atr_band", "bb_extreme", "rsi_extreme", "macd_zero_cross",
        "n_day_breakout", "long_ma_filter", "vix_threshold", "adx_filter",
        "volume_min_mult", "atr_stop", "fixed_pct_stop",
        "r_multiple_tp", "mean_revert_tp", "time_stop",
    ],
}


# --------------------------------------------------------------------------- #
# Indicator helpers (vectorized; cached per (bars_id, indicator, params))
# --------------------------------------------------------------------------- #


def _atr(bars: pd.DataFrame, period: int) -> pd.Series:
    high = bars["high"]
    low = bars["low"]
    close = bars["close"]
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def _rsi(close: pd.Series, length: int) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0)
    dn = -d.clip(upper=0)
    ru = up.ewm(alpha=1.0 / length, adjust=False).mean()
    rd = dn.ewm(alpha=1.0 / length, adjust=False).mean()
    rs = ru / rd.replace(0, 1e-12)
    return 100.0 - 100.0 / (1.0 + rs)


def _ma(close: pd.Series, length: int, kind: str = "EMA") -> pd.Series:
    if kind == "EMA":
        return close.ewm(span=length, adjust=False).mean()
    if kind == "SMA":
        return close.rolling(length).mean()
    if kind == "WMA":
        w = np.arange(1, length + 1, dtype=float)
        return close.rolling(length).apply(
            lambda x: float(np.dot(x, w) / w.sum()), raw=True,
        )
    return close.ewm(span=length, adjust=False).mean()


def _adx(bars: pd.DataFrame, length: int = 14) -> pd.Series:
    high = bars["high"]; low = bars["low"]; close = bars["close"]
    prev_h = high.shift(1); prev_l = low.shift(1); prev_c = close.shift(1)
    plus_dm = (high - prev_h).where((high - prev_h) > (prev_l - low), 0).clip(lower=0)
    minus_dm = (prev_l - low).where((prev_l - low) > (high - prev_h), 0).clip(lower=0)
    tr = pd.concat([
        high - low, (high - prev_c).abs(), (low - prev_c).abs(),
    ], axis=1).max(axis=1)
    atr_l = tr.ewm(alpha=1.0 / length, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1.0 / length, adjust=False).mean() / atr_l.replace(0, 1e-12)
    minus_di = 100 * minus_dm.ewm(alpha=1.0 / length, adjust=False).mean() / atr_l.replace(0, 1e-12)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-12)
    return dx.ewm(alpha=1.0 / length, adjust=False).mean()


# --------------------------------------------------------------------------- #
# Entry primitives — each returns (long_signal, short_signal) bool series
# --------------------------------------------------------------------------- #


def _entry_atr_band(bars, params):
    period = int(params.get("atr_period", 10))
    mult = float(params.get("atr_mult", 3.0))
    ma_len = int(params.get("ma_length", 10))
    ma_type = params.get("ma_type", "EMA")
    close = bars["close"]
    ma = _ma(close, ma_len, ma_type).to_numpy()
    atr = _atr(bars, period).to_numpy()
    n = len(bars)
    long_stop_l = np.full(n, np.nan)
    short_stop_l = np.full(n, np.nan)
    direction = np.zeros(n, dtype=int)
    for i in range(n):
        if np.isnan(atr[i]) or np.isnan(ma[i]):
            continue
        ls = ma[i] - mult * atr[i]
        ss = ma[i] + mult * atr[i]
        if i > 0 and not np.isnan(long_stop_l[i - 1]):
            ls = max(ls, long_stop_l[i - 1]) if ma[i] > long_stop_l[i - 1] else ls
            ss = min(ss, short_stop_l[i - 1]) if ma[i] < short_stop_l[i - 1] else ss
        long_stop_l[i] = ls; short_stop_l[i] = ss
        if i == 0 or direction[i - 1] == 0:
            direction[i] = 1
        else:
            prev = direction[i - 1]
            if prev == -1 and ma[i] > short_stop_l[i - 1]:
                direction[i] = 1
            elif prev == 1 and ma[i] < long_stop_l[i - 1]:
                direction[i] = -1
            else:
                direction[i] = prev
    long_sig = np.zeros(n, dtype=bool); short_sig = np.zeros(n, dtype=bool)
    for i in range(1, n):
        if direction[i] == 1 and direction[i - 1] == -1:
            long_sig[i] = True
        elif direction[i] == -1 and direction[i - 1] == 1:
            short_sig[i] = True
    return pd.Series(long_sig, index=bars.index), pd.Series(short_sig, index=bars.index), {
        "long_band": pd.Series(long_stop_l, index=bars.index),
        "short_band": pd.Series(short_stop_l, index=bars.index),
        "atr": pd.Series(atr, index=bars.index),
    }


def _entry_bb_extreme(bars, params):
    bb_len = int(params.get("bb_length", 20))
    bb_mult = float(params.get("bb_mult", 2.0))
    close = bars["close"]
    sma = close.rolling(bb_len).mean()
    std = close.rolling(bb_len).std()
    upper = sma + bb_mult * std
    lower = sma - bb_mult * std
    long_sig = (close > lower) & (close.shift(1) <= lower.shift(1))
    short_sig = (close < upper) & (close.shift(1) >= upper.shift(1))
    return long_sig.fillna(False), short_sig.fillna(False), {
        "bb_basis": sma, "bb_upper": upper, "bb_lower": lower,
    }


def _entry_rsi_extreme(bars, params):
    rsi_len = int(params.get("rsi_length", 14))
    rsi_lo = float(params.get("rsi_lo", 30.0))
    rsi_hi = float(params.get("rsi_hi", 70.0))
    close = bars["close"]
    r = _rsi(close, rsi_len)
    long_sig = (r > rsi_lo) & (r.shift(1) <= rsi_lo)
    short_sig = (r < rsi_hi) & (r.shift(1) >= rsi_hi)
    return long_sig.fillna(False), short_sig.fillna(False), {"rsi": r}


def _entry_macd_zero(bars, params):
    fast = int(params.get("macd_fast", 12))
    slow = int(params.get("macd_slow", 26))
    sig_n = int(params.get("macd_signal", 9))
    close = bars["close"]
    fast_ma = _ma(close, fast, "EMA")
    slow_ma = _ma(close, slow, "EMA")
    macd = fast_ma - slow_ma
    signal = _ma(macd, sig_n, "EMA")
    hist = macd - signal
    long_sig = (hist > 0) & (hist.shift(1) <= 0) & (macd > 0)
    short_sig = (hist < 0) & (hist.shift(1) >= 0) & (macd < 0)
    return long_sig.fillna(False), short_sig.fillna(False), {"macd": macd}


def _entry_breakout(bars, params):
    n = int(params.get("breakout_length", 20))
    close = bars["close"]
    hi = close.rolling(n).max()
    lo = close.rolling(n).min()
    long_sig = (close > hi.shift(1))
    short_sig = (close < lo.shift(1))
    return long_sig.fillna(False), short_sig.fillna(False), {"hi": hi, "lo": lo}


_ENTRY_HANDLERS = {
    "atr_band": _entry_atr_band,
    "bb_extreme": _entry_bb_extreme,
    "rsi_extreme": _entry_rsi_extreme,
    "macd_zero_cross": _entry_macd_zero,
    "n_day_breakout": _entry_breakout,
}


# --------------------------------------------------------------------------- #
# Regime filters — return bool mask of "tradeable" bars
# --------------------------------------------------------------------------- #


def _regime_long_ma(bars, params):
    n = int(params.get("regime_ma_length", 200))
    sma = bars["close"].rolling(n).mean()
    long_ok = bars["close"] > sma
    short_ok = bars["close"] < sma
    return long_ok.fillna(False), short_ok.fillna(False)


def _regime_adx(bars, params):
    adx = _adx(bars, 14)
    lo = float(params.get("adx_min", 0.0))
    hi = float(params.get("adx_max", 100.0))
    ok = (adx >= lo) & (adx <= hi)
    return ok.fillna(False), ok.fillna(False)


def _regime_vol_pct(bars, params):
    """Filter by realized 20-day vol percentile of past year."""
    rets = bars["close"].pct_change()
    vol20 = rets.rolling(20).std()
    pct = vol20.rolling(252).rank(pct=True)
    lo = float(params.get("vol_pct_min", 0.0))
    hi = float(params.get("vol_pct_max", 1.0))
    ok = (pct >= lo) & (pct <= hi)
    return ok.fillna(False), ok.fillna(False)


_REGIME_HANDLERS = {
    "long_ma_filter": _regime_long_ma,
    "adx_filter": _regime_adx,
    "vol_pct_filter": _regime_vol_pct,
}


# --------------------------------------------------------------------------- #
# Volume filter
# --------------------------------------------------------------------------- #


def _volume_ok(bars, params, on: bool):
    if not on:
        return pd.Series(True, index=bars.index)
    lookback = int(params.get("vol_lookback", 20))
    mult = float(params.get("vol_mult", 1.3))
    med = bars["volume"].rolling(lookback).median()
    return (bars["volume"] >= mult * med).fillna(False)


# --------------------------------------------------------------------------- #
# Stop / TP computation
# --------------------------------------------------------------------------- #


def _compute_stop(bars, idx, direction, params, primitive_state):
    stop_type = params.get("stop_type", "atr_mult")
    close = float(bars["close"].iloc[idx])
    if stop_type == "atr_mult":
        if "atr" in primitive_state:
            atr_v = float(primitive_state["atr"].iloc[idx])
        else:
            atr_v = float(_atr(bars, 14).iloc[idx])
        m = float(params.get("stop_atr_mult", 2.0))
        return close - m * atr_v if direction == "long" else close + m * atr_v
    if stop_type == "opposite_band":
        if direction == "long" and "long_band" in primitive_state:
            return float(primitive_state["long_band"].iloc[idx])
        if direction == "short" and "short_band" in primitive_state:
            return float(primitive_state["short_band"].iloc[idx])
        if direction == "long" and "bb_lower" in primitive_state:
            return float(primitive_state["bb_lower"].iloc[idx])
        if direction == "short" and "bb_upper" in primitive_state:
            return float(primitive_state["bb_upper"].iloc[idx])
        # fall through to fixed_pct
    if stop_type == "fixed_pct" or True:
        pct = float(params.get("stop_pct", 0.03))
        return close * (1 - pct) if direction == "long" else close * (1 + pct)


def _compute_tp(bars, idx, direction, entry, stop, params, primitive_state):
    tp_type = params.get("tp_type", "r_multiple_single")
    if tp_type == "r_multiple_single":
        m = float(params.get("tp_r_multiple", 2.0))
        r = abs(entry - stop)
        return entry + m * r if direction == "long" else entry - m * r
    if tp_type == "mean_revert" and "bb_basis" in primitive_state:
        return float(primitive_state["bb_basis"].iloc[idx])
    if tp_type == "time_only":
        return None
    # default to r_multiple
    r = abs(entry - stop)
    return entry + 2 * r if direction == "long" else entry - 2 * r


# --------------------------------------------------------------------------- #
# Main detect()
# --------------------------------------------------------------------------- #


def detect(bars: pd.DataFrame, params: dict) -> list[Signal]:
    """Generate signals from the meta-strategy config.

    Required keys in `params`:
      - entry_primitive: one of _ENTRY_HANDLERS keys
      - regime_filters: list of _REGIME_HANDLERS keys (any subset)
      - use_volume_filter: bool
      - stop_type, tp_type
      - all primitive-specific params used by chosen primitives

    Optional:
      - long_only: bool
      - time_stop_bars: int
    """
    entry_id = params.get("entry_primitive", "atr_band")
    handler = _ENTRY_HANDLERS.get(entry_id)
    if handler is None:
        return []

    long_sig, short_sig, prim_state = handler(bars, params)

    # Apply regime filters
    long_ok = pd.Series(True, index=bars.index)
    short_ok = pd.Series(True, index=bars.index)
    for rf in params.get("regime_filters", []):
        h = _REGIME_HANDLERS.get(rf)
        if h is None:
            continue
        l_ok, s_ok = h(bars, params)
        long_ok = long_ok & l_ok
        short_ok = short_ok & s_ok

    vol_ok = _volume_ok(bars, params, on=bool(params.get("use_volume_filter", False)))
    long_sig = long_sig & long_ok & vol_ok
    short_sig = short_sig & short_ok & vol_ok

    if params.get("long_only", False):
        short_sig = pd.Series(False, index=bars.index)

    time_stop = params.get("time_stop_bars")
    if time_stop is not None:
        time_stop = int(time_stop)

    signals: list[Signal] = []
    close = bars["close"]
    for i in range(len(bars)):
        if not (long_sig.iloc[i] or short_sig.iloc[i]):
            continue
        c = float(close.iloc[i])
        if math.isnan(c):
            continue
        direction = "long" if long_sig.iloc[i] else "short"
        try:
            stop = _compute_stop(bars, i, direction, params, prim_state)
        except Exception:
            continue
        if stop is None or math.isnan(stop):
            continue
        if direction == "long" and stop >= c:
            continue
        if direction == "short" and stop <= c:
            continue
        try:
            tp = _compute_tp(bars, i, direction, c, stop, params, prim_state)
        except Exception:
            tp = None
        if tp is not None and math.isnan(tp):
            tp = None
        signals.append(Signal(
            bar_idx=i, direction=direction,
            entry_price=c, stop_price=stop, take_profit_price=tp,
            time_stop_bars=time_stop,
            note=f"e={entry_id} r={len(params.get('regime_filters', []))} v={int(vol_ok.iloc[i])}",
        ))
    return signals
