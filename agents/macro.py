"""Macro lens — pure function, no external API calls.

Computes a ``MacroContext`` snapshot from cached SPY and VIX bars at
``as_of_ts``. Does not emit Signals; instead, the dict it returns is
attached to every Signal the other lenses produce, so the portfolio
manager and universal PQS modifiers can use market-wide context.

Output fields:
    spy_trend_20d       — SPY 20-day pct return (float, decimal not %)
    spy_above_sma200    — bool
    vix_level           — latest VIX close
    vix_regime          — 'low' (<15), 'medium' (15-25), 'high' (25-35),
                          'extreme' (>35)
    sector_rs           — (not computed here; the analyst passes
                          per-symbol sector context in at the call site
                          if needed — macro lens stays symbol-agnostic)

If SPY or VIX bars aren't available the corresponding fields are
``None``. Callers treat ``None`` as "unknown, skip this modifier".

Pure function of (as_of_ts). Reads only cached bars via data_service.
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from services.data_service import DataNotAvailableError, get_bars

logger = logging.getLogger(__name__)

SPY = "SPY"
VIX = "^VIX"
LOOKBACK_SPY = 220  # enough for 20-day return + sma_200


async def compute_macro_context(
    as_of_ts: pd.Timestamp | None = None,
) -> dict[str, Any]:
    """Build the macro context snapshot. Errors degrade to partial output."""
    ctx: dict[str, Any] = {
        "spy_trend_20d": None,
        "spy_above_sma200": None,
        "vix_level": None,
        "vix_regime": None,
    }

    # SPY trend
    try:
        spy = await get_bars(SPY, "1d", as_of_ts=as_of_ts, min_bars=LOOKBACK_SPY)
    except DataNotAvailableError as e:
        logger.warning("macro: SPY bars unavailable: %s", e)
        spy = None

    if spy is not None and len(spy) >= 20:
        close_now = float(spy["close"].iloc[-1])
        close_20 = float(spy["close"].iloc[-21])
        ctx["spy_trend_20d"] = round((close_now - close_20) / close_20, 4)
        if len(spy) >= 200:
            sma200 = float(spy["close"].tail(200).mean())
            ctx["spy_above_sma200"] = close_now > sma200

    # VIX level + regime
    try:
        vix = await get_bars(VIX, "1d", as_of_ts=as_of_ts, min_bars=5)
    except DataNotAvailableError as e:
        logger.warning("macro: VIX bars unavailable: %s", e)
        vix = None

    if vix is not None and not vix.empty:
        vix_level = float(vix["close"].iloc[-1])
        ctx["vix_level"] = round(vix_level, 2)
        if vix_level < 15:
            ctx["vix_regime"] = "low"
        elif vix_level < 25:
            ctx["vix_regime"] = "medium"
        elif vix_level < 35:
            ctx["vix_regime"] = "high"
        else:
            ctx["vix_regime"] = "extreme"

    return ctx
