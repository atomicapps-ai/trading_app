"""analyst.py — multi-lens signal generator.

Runs the four configured lenses on a shortlist symbol and emits
``Signal`` objects for any pattern / catalyst whose score clears the
``min_signal_strength`` threshold (default 0.55 == PQS 55).

Lenses
------
* **technical**   — the pattern detectors (``agents/detectors/``).
                    Primary for swing trades.
* **macro**       — context only (vix, spy trend). Does NOT emit its
                    own Signal; the dict it produces is attached to
                    every other lens' signals.
* **sentiment**   — OPT (Phase 4 follow-up). VADER + Alpaca headlines.
* **fundamental** — OPT (Phase 4 follow-up). EDGAR filings.

Contract
--------
All lenses are pure functions of
``(symbol, bars, news, fundamentals, macro, config, as_of_ts)``. Live
and Phase 5 backtest call the same code; the ``as_of_ts`` argument is
the only "now" any lens sees.

This session ships the technical + macro lenses. Sentiment and
fundamental stubs live at the bottom of this file and return ``[]``
until their follow-up work lands.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import yaml

from agents.detectors import ALL_DETECTORS
from models.pattern import PatternResult
from models.signal import Evidence, KeyLevels, Signal
from services.data_service import DataNotAvailableError, get_bars
from services.indicator_service import add_indicators
from services.settings_service import STRATEGY_CONFIG_DIR, Settings

logger = logging.getLogger(__name__)

Lens = Literal["technical", "fundamental", "sentiment", "macro"]

DEFAULT_MIN_SIGNAL_STRENGTH = 0.55  # PQS 55 floor per phase4 spec


# --------------------------------------------------------------------------- #
# Strategy config loader
# --------------------------------------------------------------------------- #


def load_strategy_config(
    strategy_name: str = "swing_momentum",
    config_dir: Path = STRATEGY_CONFIG_DIR,
) -> dict[str, Any]:
    path = config_dir / f"{strategy_name}.yaml"
    if not path.exists():
        logger.warning("strategy config missing: %s — using defaults", path)
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


# --------------------------------------------------------------------------- #
# Technical lens — runs every detector, returns PatternResults
# --------------------------------------------------------------------------- #


def run_lens_technical(
    symbol: str,
    daily: pd.DataFrame,
    hourly: pd.DataFrame,
    config: dict[str, Any],
    as_of_ts: pd.Timestamp | None,
    macro_context: dict[str, Any] | None,
) -> list[PatternResult]:
    """Run every registered detector. Return the ones that fired.

    Detectors are pure functions — no ``await`` needed. We iterate
    in-process; async only matters at the bar / news fetch layer above.
    """
    results: list[PatternResult] = []
    for name, fn in ALL_DETECTORS.items():
        try:
            result = fn(daily, hourly, config, as_of_ts, macro_context=macro_context)
        except Exception as e:  # noqa: BLE001
            logger.warning("detector %s raised on %s: %s", name, symbol, e)
            continue
        if result is not None:
            results.append(result)
    return results


# --------------------------------------------------------------------------- #
# PatternResult → Signal
# --------------------------------------------------------------------------- #


def pattern_to_signal(
    symbol: str,
    pattern: PatternResult,
    lens: Lens = "technical",
    timeframe: str = "swing_days",
) -> Signal:
    """Emit a Signal object the portfolio_manager can consume.

    The analyst writes the ``key_levels`` and ``evidence`` fields; the
    portfolio_manager converts these (plus risk rules) into the
    TradePlan's entry / stop / tp legs.
    """
    strength = max(0.0, min(1.0, pattern.pqs_total / 100.0))
    evidence_objs = [
        Evidence(type=e.get("type", "pattern"), ref=e.get("ref", ""))
        for e in pattern.evidence_items
    ]
    return Signal(
        symbol=symbol,
        lens=lens,  # type: ignore[arg-type]
        direction=pattern.direction,  # type: ignore[arg-type]
        strength=strength,
        timeframe=timeframe,  # type: ignore[arg-type]
        key_levels=KeyLevels(
            support=pattern.stop_price if pattern.direction == "long" else None,
            resistance=pattern.stop_price if pattern.direction == "short" else None,
            invalidation=pattern.invalidation_level,
        ),
        evidence=evidence_objs,
        invalidation_condition=pattern.invalidation_condition,
    )


# --------------------------------------------------------------------------- #
# Main orchestration
# --------------------------------------------------------------------------- #


class Analyst:
    """Per-symbol multi-lens signal generator."""

    def __init__(
        self,
        settings: Settings,
        strategy_name: str = "swing_momentum",
    ) -> None:
        self._settings = settings
        self._strategy_config = load_strategy_config(strategy_name)
        self._strategy_name = strategy_name
        self._min_strength = float(
            self._strategy_config.get("min_signal_strength", DEFAULT_MIN_SIGNAL_STRENGTH)
        )

    async def run(
        self,
        symbol: str,
        macro_context: dict[str, Any] | None = None,
        as_of_ts: pd.Timestamp | None = None,
    ) -> list[Signal]:
        """Run every enabled lens on one symbol. Returns qualifying signals."""
        # Bars — daily primary, hourly confirmation (may be unavailable)
        try:
            daily = await get_bars(symbol, "1d", as_of_ts=as_of_ts, min_bars=210)
        except DataNotAvailableError as e:
            logger.info("analyst: skipping %s — %s", symbol, e)
            return []
        try:
            hourly = await get_bars(symbol, "1h", as_of_ts=as_of_ts, min_bars=50)
        except DataNotAvailableError:
            hourly = pd.DataFrame()

        daily_ind = add_indicators(daily)
        hourly_ind = add_indicators(hourly) if not hourly.empty else hourly

        # Technical lens — the main signal producer
        patterns = run_lens_technical(
            symbol, daily_ind, hourly_ind,
            self._strategy_config,
            as_of_ts=as_of_ts,
            macro_context=macro_context,
        )

        # Other lenses — stubs for this session
        patterns.extend(await self._run_lens_sentiment_stub(symbol, as_of_ts))
        patterns.extend(await self._run_lens_fundamental_stub(symbol, as_of_ts))

        # Score floor
        qualifying = [p for p in patterns if p.pqs_total / 100.0 >= self._min_strength]
        logger.info(
            "Analyst %s: %d patterns fired, %d cleared PQS>=%.2f",
            symbol, len(patterns), len(qualifying), self._min_strength,
        )
        return [pattern_to_signal(symbol, p) for p in qualifying]

    # ---- Non-technical lens stubs ------------------------------------- #

    async def _run_lens_sentiment_stub(
        self, symbol: str, as_of_ts: pd.Timestamp | None,
    ) -> list[PatternResult]:
        # Follow-up: VADER + Alpaca News. Needs ALPACA_API_KEY set.
        return []

    async def _run_lens_fundamental_stub(
        self, symbol: str, as_of_ts: pd.Timestamp | None,
    ) -> list[PatternResult]:
        # Follow-up: EDGAR 8-K / 10-Q / 10-K event detection.
        return []


# --------------------------------------------------------------------------- #
# Parallel runner — shortlist -> dict[symbol, list[Signal]]
# --------------------------------------------------------------------------- #


async def run_analyst_on_shortlist(
    shortlist: list[str],
    settings: Settings,
    macro_context: dict[str, Any] | None = None,
    as_of_ts: pd.Timestamp | None = None,
    strategy_name: str = "swing_momentum",
    max_concurrency: int = 16,
) -> dict[str, list[Signal]]:
    """Run the analyst across every shortlist symbol in parallel.

    Per-symbol failures are logged and the symbol drops out silently —
    one bad ticker never kills a pipeline run.
    """
    analyst = Analyst(settings, strategy_name=strategy_name)
    sem = asyncio.Semaphore(max_concurrency)

    async def _one(sym: str) -> tuple[str, list[Signal]]:
        async with sem:
            try:
                sigs = await analyst.run(sym, macro_context=macro_context, as_of_ts=as_of_ts)
                return sym, sigs
            except Exception as e:  # noqa: BLE001
                logger.warning("analyst failed on %s: %s", sym, e)
                return sym, []

    results = await asyncio.gather(*(_one(s) for s in shortlist))
    return {sym: sigs for sym, sigs in results if sigs}
