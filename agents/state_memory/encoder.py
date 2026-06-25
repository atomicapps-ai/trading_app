"""Per-bar state encoder.

Given an OHLCV DataFrame indexed by timestamp, produce an 8-dimensional
feature vector for each bar describing the market state at that moment.

Features (in order):
    0. rsi_norm         — RSI(14) / 100, range [0, 1]
    1. macd_slope_atr   — macd_line.diff() / atr_14, scale-invariant
    2. adx_norm         — ADX(14) / 100
    3. dist_vwap        — (close - vwap) / vwap, unitless return
    4. dist_ema20       — (close - ema_20) / ema_20
    5. range_atr        — (high - low) / atr_14, candle range in ATR units
    6. log_relvol       — log(volume / volume_sma_20), centered at 0
    7. candle_sentiment — ((close - open) / (high - low)) signed body, [-1, 1]

Bars where any required indicator hasn't warmed up are flagged invalid.
"""
from __future__ import annotations

from typing import Tuple

import numpy as np
import pandas as pd

from services import indicator_service

FEATURE_NAMES: list[str] = [
    "rsi_norm",
    "macd_slope_atr",
    "adx_norm",
    "dist_vwap",
    "dist_ema20",
    "range_atr",
    "log_relvol",
    "candle_sentiment",
]
N_FEATURES: int = len(FEATURE_NAMES)


def encode_bars(df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
    """Encode every bar into the 8-dim feature space.

    Returns:
        features: float32 array of shape (N, 8). Invalid rows hold NaN.
        valid_mask: bool array of shape (N,). True where the row has no NaN
                    in features AND has the upstream indicators warmed up.
    """
    if not {"open", "high", "low", "close", "volume"}.issubset(df.columns):
        raise ValueError("encode_bars: df missing OHLCV columns")

    if df.index.tz is None:
        df = df.copy()
        df.index = df.index.tz_localize("UTC")

    ind = indicator_service.add_indicators(df)

    n = len(ind)
    feats = np.full((n, N_FEATURES), np.nan, dtype=np.float32)

    rsi = ind["rsi_14"].to_numpy(dtype=np.float64)
    atr = ind["atr_14"].to_numpy(dtype=np.float64)
    adx = ind["adx_14"].to_numpy(dtype=np.float64)
    macd = ind["macd_line"].to_numpy(dtype=np.float64)
    vwap = ind["vwap"].to_numpy(dtype=np.float64)
    ema20 = ind["ema_20"].to_numpy(dtype=np.float64)
    vol_sma = ind["volume_sma_20"].to_numpy(dtype=np.float64)

    o = df["open"].to_numpy(dtype=np.float64)
    h = df["high"].to_numpy(dtype=np.float64)
    l = df["low"].to_numpy(dtype=np.float64)
    c = df["close"].to_numpy(dtype=np.float64)
    v = df["volume"].to_numpy(dtype=np.float64)

    macd_slope = np.diff(macd, prepend=np.nan)

    with np.errstate(divide="ignore", invalid="ignore"):
        feats[:, 0] = rsi / 100.0
        feats[:, 1] = macd_slope / atr
        feats[:, 2] = adx / 100.0
        feats[:, 3] = (c - vwap) / vwap
        feats[:, 4] = (c - ema20) / ema20
        feats[:, 5] = (h - l) / atr
        feats[:, 6] = np.log(v / vol_sma)
        rng = h - l
        body = c - o
        feats[:, 7] = np.where(rng > 0, body / rng, 0.0)

    feats[~np.isfinite(feats)] = np.nan
    valid_mask = ~np.isnan(feats).any(axis=1)
    return feats, valid_mask
