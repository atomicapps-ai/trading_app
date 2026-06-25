"""baseline_service — the control Kronos must beat.

A geometric Brownian motion (GBM) forecaster. It estimates drift (mu) and volatility
(sigma) from recent log returns, then Monte-Carlo simulates `n_paths` forward
trajectories. Returns the same ForecastDistribution shape as kronos_service so the two
are directly comparable on p_up / expected R / hit probabilities / Brier (see
strategies/KRONOS_UPGRADE_PROPOSAL.md §1 and §5).

The 5-minute BTC study found Kronos-small statistically indistinguishable from exactly
this baseline out-of-sample — so until Kronos beats GBM on a chronological OOS split,
there is no edge worth surfacing.
"""
from __future__ import annotations

import logging
import math
import random

import pandas as pd

from models.forecast import ForecastDistribution, ForecastPath

logger = logging.getLogger(__name__)


def gbm_forecast(
    *,
    symbol: str,
    interval: str,
    bars: pd.DataFrame,
    pred_len: int = 10,
    n_paths: int = 30,
    lookback: int = 250,
    seed: int | None = None,
    intrabar_range: bool = True,
) -> ForecastDistribution:
    """Geometric Brownian motion Monte-Carlo forecast.

    `bars` needs at least a 'close' column (oldest-first) and a DatetimeIndex or a
    'timestamps' column. `intrabar_range` synthesizes a high/low around each simulated
    close (scaled to recent average true range) so hit_probabilities() is meaningful.
    """
    rng = random.Random(seed)
    df = bars.copy()
    if "timestamps" in df.columns:
        ts = pd.to_datetime(df["timestamps"])
    else:
        ts = pd.Series(pd.to_datetime(df.index))

    closes = [float(c) for c in df["close"].tolist()][-lookback:]
    if len(closes) < 30:
        raise ValueError("need >=30 closes to estimate GBM parameters")

    log_rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    mu = sum(log_rets) / len(log_rets)
    var = sum((r - mu) ** 2 for r in log_rets) / (len(log_rets) - 1)
    sigma = math.sqrt(var)
    last_close = closes[-1]

    # average relative range, for synthetic intrabar high/low
    if intrabar_range and {"high", "low"}.issubset(df.columns):
        hi = [float(x) for x in df["high"].tolist()][-lookback:]
        lo = [float(x) for x in df["low"].tolist()][-lookback:]
        rel_range = sum((h - l) / c for h, l, c in zip(hi, lo, closes) if c) / len(closes)
    else:
        rel_range = sigma  # fallback

    paths: list[ForecastPath] = []
    for _ in range(n_paths):
        price = last_close
        close, high, low = [], [], []
        for _step in range(pred_len):
            shock = rng.gauss(0.0, 1.0)
            price = price * math.exp((mu - 0.5 * var) + sigma * shock)
            half = price * rel_range / 2.0
            close.append(price)
            high.append(price + half)
            low.append(price - half)
        paths.append(ForecastPath(close=close, high=high, low=low))

    logger.debug("GBM %s: mu=%.5f sigma=%.5f rel_range=%.4f", symbol, mu, sigma, rel_range)
    return ForecastDistribution.build(
        source="gbm-baseline",
        symbol=symbol,
        interval=interval,
        as_of=pd.Timestamp(ts.iloc[-1]).isoformat(),
        last_close=last_close,
        paths=paths,
    )
