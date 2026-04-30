"""indicator_service.py — technical indicator calculations.

All agents and lenses compute indicators through this module — no
direct calls to pandas-ta / talib elsewhere. The canonical entry
point is `add_indicators(df)`, which appends every standard column
the pattern detectors expect.

Why hand-rolled (no pandas-ta dep)
----------------------------------
pandas-ta's released build (0.3.14b) has known incompat with numpy
2.x (the project is on numpy 2.4). Rather than pin pandas-ta to a
community fork or downgrade numpy, we compute the ~15 indicators we
need directly in pandas/numpy. Upside: deterministic, version-stable,
no hidden state, trivially backtest-safe (pure functions over a
DataFrame window).

Column naming convention (lowercase, snake_case)
------------------------------------------------
    rsi_14, atr_14, atr_14_pct
    sma_20, sma_50, sma_200, ema_20
    bb_upper_20, bb_middle_20, bb_lower_20, bb_width_20
    kc_upper_20, kc_middle_20, kc_lower_20
    squeeze_on (bool), squeeze_fired (bool)
    momentum                         (TTM-style rolling linreg residual)
    macd_line, macd_signal, macd_hist
    volume_sma_20, volume_ratio      (close / volume_sma_20)
    vwap                             (session-reset for 1h bars; rolling-cumulative for 1d)

Every public function is a pure function of its input DataFrame.
Never modifies the caller's df (all ops go through .copy()).
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Primitives
# --------------------------------------------------------------------------- #


def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(window=n, min_periods=n).mean()


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def _wilder_rma(s: pd.Series, n: int) -> pd.Series:
    """Wilder's smoothed moving average — α = 1/n. Used by RSI and ATR.

    Identical math to `ewm(alpha=1/n, adjust=False)` but we keep it
    explicit so the intent is obvious to a future reader.
    """
    return s.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


# --------------------------------------------------------------------------- #
# Indicator components
# --------------------------------------------------------------------------- #


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    """Wilder's RSI. Classic formulation — agrees with TradingView."""
    delta = close.diff()
    up = delta.clip(lower=0.0)
    down = (-delta).clip(lower=0.0)
    avg_up = _wilder_rma(up, n)
    avg_down = _wilder_rma(down, n)
    rs = avg_up / avg_down.replace(0.0, np.nan)
    return (100.0 - (100.0 / (1.0 + rs))).fillna(50.0)


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr


def _atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    n: int = 14,
) -> pd.Series:
    """Wilder's ATR."""
    return _wilder_rma(_true_range(high, low, close), n)


def _adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    n: int = 14,
) -> pd.Series:
    """Wilder's Average Directional Index — agrees with TradingView's ADX(14)."""
    up = high.diff()
    down = -low.diff()
    plus_dm  = up.where((up > down) & (up > 0), 0.0).fillna(0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0).fillna(0.0)
    tr_n     = _wilder_rma(_true_range(high, low, close), n)
    plus_di  = 100.0 * _wilder_rma(plus_dm, n)  / tr_n.replace(0.0, np.nan)
    minus_di = 100.0 * _wilder_rma(minus_dm, n) / tr_n.replace(0.0, np.nan)
    dx       = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    return _wilder_rma(dx, n)


def _bollinger(
    close: pd.Series, n: int = 20, mult: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = _sma(close, n)
    std = close.rolling(window=n, min_periods=n).std(ddof=0)
    upper = mid + mult * std
    lower = mid - mult * std
    return upper, mid, lower


def _keltner(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    n: int = 20,
    mult: float = 1.5,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = _ema(close, n)
    atr_series = _atr(high, low, close, n=n)
    upper = mid + mult * atr_series
    lower = mid - mult * atr_series
    return upper, mid, lower


def _macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    macd_line = _ema(close, fast) - _ema(close, slow)
    sig = _ema(macd_line, signal)
    hist = macd_line - sig
    return macd_line, sig, hist


def _ttm_momentum(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    n: int = 20,
) -> pd.Series:
    """TTM squeeze momentum: rolling linear-regression residual of
    `close - midline`, where midline is the average of the n-bar
    donchian midpoint and n-bar SMA.

    Captures the TTM Squeeze histogram behavior (positive + green /
    negative + red) without a pandas-ta dependency.
    """
    donchian = 0.5 * (high.rolling(n, min_periods=n).max() + low.rolling(n, min_periods=n).min())
    sma_c = _sma(close, n)
    ref = 0.5 * (donchian + sma_c)
    delta = close - ref

    x = np.arange(n, dtype=float)
    x_mean = x.mean()
    x_dev = x - x_mean
    x_var = (x_dev ** 2).sum()

    def _linreg_last(window: np.ndarray) -> float:
        if np.isnan(window).any():
            return np.nan
        y_mean = window.mean()
        slope = (x_dev * (window - y_mean)).sum() / x_var
        intercept = y_mean - slope * x_mean
        return slope * (n - 1) + intercept  # value at the last bar

    return delta.rolling(window=n, min_periods=n).apply(_linreg_last, raw=True)


def _squeeze_flags(
    bb_upper: pd.Series,
    bb_lower: pd.Series,
    kc_upper: pd.Series,
    kc_lower: pd.Series,
    min_bars_on: int = 6,
) -> tuple[pd.Series, pd.Series]:
    """TTM Squeeze flags.

    squeeze_on    — BB is inside KC (compression active)
    squeeze_fired — first bar squeeze_on flips False after being True
                    for at least `min_bars_on` consecutive bars
    """
    on = (bb_upper < kc_upper) & (bb_lower > kc_lower)

    # Count consecutive True run lengths ending at each bar.
    on_int = on.astype(int).to_numpy()
    run_len = np.zeros_like(on_int)
    c = 0
    for i, v in enumerate(on_int):
        c = c + 1 if v else 0
        run_len[i] = c

    run_prev = np.concatenate([[0], run_len[:-1]])
    fired = (~on) & (run_prev >= min_bars_on)

    return on, pd.Series(fired, index=on.index)


def _session_vwap(
    high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series
) -> pd.Series:
    """Session-reset VWAP.

    For daily bars there is no intraday session to reset, so we compute
    a rolling cumulative VWAP since the start of the frame (yielding a
    long-running mean that's useful as a reference line).

    For intraday bars (detected by the index step being < 1 day), we
    reset the numerator and denominator at each UTC midnight — close
    enough to a US-equities session boundary for swing pattern work
    (the pattern detectors that care about VWAP use it as a daily
    mean-reversion reference, not an intraday micro-structure signal).
    """
    typical = (high + low + close) / 3.0
    pv = typical * volume

    if len(high) < 2:
        return pd.Series(np.nan, index=high.index)

    step = high.index[1] - high.index[0]
    is_intraday = step < pd.Timedelta(days=1)

    if not is_intraday:
        cum_pv = pv.cumsum()
        cum_v = volume.cumsum().replace(0.0, np.nan)
        return cum_pv / cum_v

    # Intraday: reset each UTC date.
    date_key = high.index.tz_convert("UTC").date
    key_series = pd.Series(date_key, index=high.index)
    cum_pv = pv.groupby(key_series).cumsum()
    cum_v = volume.groupby(key_series).cumsum().replace(0.0, np.nan)
    return cum_pv / cum_v


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Append the full standard indicator column set.

    Input df must contain: open, high, low, close, volume.
    Never modifies the input — returns a new DataFrame.

    Rows for which an indicator has not yet "warmed up" (< n bars of
    history) are left as NaN rather than filled. Pattern detectors
    must tolerate leading NaNs — they already check `len(df) >=
    min_required_bars` for this reason.
    """
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"add_indicators: missing required columns {missing}")

    out = df.copy()
    close = out["close"]
    high = out["high"]
    low = out["low"]
    volume = out["volume"]

    # Moving averages
    out["sma_20"] = _sma(close, 20)
    out["sma_50"] = _sma(close, 50)
    out["sma_200"] = _sma(close, 200)
    out["ema_20"] = _ema(close, 20)

    # RSI, ATR, ADX
    out["rsi_14"] = _rsi(close, 14)
    out["atr_14"] = _atr(high, low, close, 14)
    out["atr_14_pct"] = 100.0 * out["atr_14"] / close
    out["adx_14"] = _adx(high, low, close, 14)

    # Bollinger + Keltner → Squeeze
    bb_u, bb_m, bb_l = _bollinger(close, 20, 2.0)
    kc_u, kc_m, kc_l = _keltner(high, low, close, 20, 1.5)
    out["bb_upper_20"] = bb_u
    out["bb_middle_20"] = bb_m
    out["bb_lower_20"] = bb_l
    out["bb_width_20"] = (bb_u - bb_l) / bb_m.replace(0.0, np.nan)
    out["kc_upper_20"] = kc_u
    out["kc_middle_20"] = kc_m
    out["kc_lower_20"] = kc_l
    on, fired = _squeeze_flags(bb_u, bb_l, kc_u, kc_l, min_bars_on=6)
    out["squeeze_on"] = on
    out["squeeze_fired"] = fired
    out["momentum"] = _ttm_momentum(high, low, close, 20)

    # MACD
    mline, msig, mhist = _macd(close, 12, 26, 9)
    out["macd_line"] = mline
    out["macd_signal"] = msig
    out["macd_hist"] = mhist

    # Volume
    out["volume_sma_20"] = _sma(volume, 20)
    out["volume_ratio"] = volume / out["volume_sma_20"].replace(0.0, np.nan)

    # VWAP
    out["vwap"] = _session_vwap(high, low, close, volume)

    return out


def calc_squeeze(
    df: pd.DataFrame,
    bb_period: int = 20,
    bb_mult: float = 2.0,
    kc_period: int = 20,
    kc_mult: float = 1.5,
    min_squeeze_bars: int = 6,
) -> pd.DataFrame:
    """Standalone squeeze computation with tunable parameters.

    Returns a new DataFrame with `squeeze_on`, `squeeze_fired`,
    `momentum` appended. Useful for pattern detectors that need
    per-strategy thresholds different from the standard set.
    """
    required = {"high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"calc_squeeze: missing required columns {missing}")

    out = df.copy()
    bb_u, _, bb_l = _bollinger(out["close"], bb_period, bb_mult)
    kc_u, _, kc_l = _keltner(out["high"], out["low"], out["close"], kc_period, kc_mult)
    on, fired = _squeeze_flags(bb_u, bb_l, kc_u, kc_l, min_bars_on=min_squeeze_bars)
    out["squeeze_on"] = on
    out["squeeze_fired"] = fired
    out["momentum"] = _ttm_momentum(out["high"], out["low"], out["close"], bb_period)
    return out


def calc_rsi_divergence(
    df: pd.DataFrame,
    period: int = 14,
    lookback: int = 50,
    min_pivot_distance: int = 5,
) -> pd.DataFrame:
    """Detect RSI-vs-price divergences within a trailing window.

    Adds columns:
        bullish_div   — price made a lower low, RSI made a higher low
        bearish_div   — price made a higher high, RSI made a lower high
        div_class     — "A" / "B" / "C" / None, strength tier
        div_rsi_diff  — RSI gap between the two pivots (positive number)

    The algorithm finds the two most recent swing pivots within
    `lookback` bars using a simple 5-bar local-extreme rule
    (configurable via `min_pivot_distance`). This is the standard
    retail-grade divergence detector — deterministic and cheap.

    Class tiers are based on RSI level at the second pivot:
        A: RSI <= 30 (bullish)  /  RSI >= 70 (bearish)  — strong
        B: 30 < RSI <= 40       /  60 <= RSI < 70       — moderate
        C: otherwise                                    — weak
    """
    required = {"high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"calc_rsi_divergence: missing required columns {missing}")

    out = df.copy()
    close = out["close"]
    high = out["high"]
    low = out["low"]
    rsi = out["rsi_14"] if "rsi_14" in out.columns else _rsi(close, period)

    # Local extremes: bar i is a pivot if it's the min/max over the
    # surrounding 2*min_pivot_distance+1 bars.
    d = min_pivot_distance
    low_roll = low.rolling(2 * d + 1, center=True).min()
    high_roll = high.rolling(2 * d + 1, center=True).max()
    is_swing_low = (low == low_roll) & low.notna()
    is_swing_high = (high == high_roll) & high.notna()

    bullish = np.zeros(len(out), dtype=bool)
    bearish = np.zeros(len(out), dtype=bool)
    div_class: list[str | None] = [None] * len(out)
    div_rsi_diff = np.full(len(out), np.nan)

    low_idx = np.where(is_swing_low.to_numpy())[0]
    high_idx = np.where(is_swing_high.to_numpy())[0]

    low_arr = low.to_numpy()
    high_arr = high.to_numpy()
    rsi_arr = rsi.to_numpy()

    # Bullish: most recent two swing lows; price lower, RSI higher.
    if len(low_idx) >= 2:
        i2 = low_idx[-1]
        for i1 in reversed(low_idx[:-1]):
            if i2 - i1 > lookback:
                break
            if low_arr[i2] < low_arr[i1] and rsi_arr[i2] > rsi_arr[i1]:
                bullish[i2] = True
                diff = rsi_arr[i2] - rsi_arr[i1]
                div_rsi_diff[i2] = diff
                r = rsi_arr[i2]
                if r <= 30:
                    div_class[i2] = "A"
                elif r <= 40:
                    div_class[i2] = "B"
                else:
                    div_class[i2] = "C"
                break

    # Bearish: most recent two swing highs; price higher, RSI lower.
    if len(high_idx) >= 2:
        i2 = high_idx[-1]
        for i1 in reversed(high_idx[:-1]):
            if i2 - i1 > lookback:
                break
            if high_arr[i2] > high_arr[i1] and rsi_arr[i2] < rsi_arr[i1]:
                bearish[i2] = True
                diff = rsi_arr[i1] - rsi_arr[i2]
                div_rsi_diff[i2] = diff
                r = rsi_arr[i2]
                if r >= 70:
                    div_class[i2] = "A"
                elif r >= 60:
                    div_class[i2] = "B"
                else:
                    div_class[i2] = "C"
                break

    out["bullish_div"] = bullish
    out["bearish_div"] = bearish
    out["div_class"] = div_class
    out["div_rsi_diff"] = div_rsi_diff
    return out


def calc_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """Standalone VWAP computation (session-reset for intraday)."""
    required = {"high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"calc_vwap: missing required columns {missing}")

    out = df.copy()
    out["vwap"] = _session_vwap(out["high"], out["low"], out["close"], out["volume"])
    return out
