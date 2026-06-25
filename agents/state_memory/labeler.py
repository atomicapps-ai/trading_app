"""Forward-return labels for state-memory bars.

For each bar t, computes close[t + N] / close[t] - 1 at horizons:
    1h, 4h, 1d, 5d
where N depends on the bar interval.

Bars that don't have N future bars available get NaN.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

HORIZONS: list[str] = ["fwd_1h", "fwd_4h", "fwd_1d", "fwd_5d"]

# Trading-day bar counts per interval. US equities: ~6.5h regular session.
# 30m: 13 bars/day; 15m: 26 bars/day; 1h: 7 bars/day; 5m: 78 bars/day.
_HORIZON_BARS: dict[str, dict[str, int]] = {
    "30m": {"fwd_1h": 2,  "fwd_4h": 8,  "fwd_1d": 13, "fwd_5d": 65},
    "15m": {"fwd_1h": 4,  "fwd_4h": 16, "fwd_1d": 26, "fwd_5d": 130},
    "1h":  {"fwd_1h": 1,  "fwd_4h": 4,  "fwd_1d": 7,  "fwd_5d": 35},
    "5m":  {"fwd_1h": 12, "fwd_4h": 48, "fwd_1d": 78, "fwd_5d": 390},
}


def horizon_bars(interval: str) -> dict[str, int]:
    if interval not in _HORIZON_BARS:
        raise ValueError(
            f"unsupported interval {interval!r}; expected one of {sorted(_HORIZON_BARS)}"
        )
    return _HORIZON_BARS[interval]


def label_bars(df: pd.DataFrame, interval: str) -> dict[str, np.ndarray]:
    """Compute forward-return labels at every horizon for the given bars.

    Returns a dict mapping horizon name -> float32 array aligned with df.index.
    Bars without enough future history get NaN at that horizon.
    """
    if "close" not in df.columns:
        raise ValueError("label_bars: df missing 'close'")
    bars_per_horizon = horizon_bars(interval)
    close = df["close"].to_numpy(dtype=np.float64)
    n = len(close)
    out: dict[str, np.ndarray] = {}
    for horizon, k in bars_per_horizon.items():
        future = np.full(n, np.nan, dtype=np.float64)
        if k < n:
            future[: n - k] = close[k:] / close[: n - k] - 1.0
        out[horizon] = future.astype(np.float32)
    return out
