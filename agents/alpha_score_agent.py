"""alpha_score_agent.py — composes the four-pillar weighted Alpha Score.

This is the single entry point the strategy loop uses to ask
"should we look at this symbol right now?". It consults:

* ``services/relative_strength_service``         — Layer-3 (40 %).
* ``services/macro_pulse_service``               — Layer-2 (25 %).
* ``services/volume_profile_service``            — Layer-3 (20 %).
* ``services/news_sentiment_engine``             — Layer-1 (15 %).
* ``services/economic_calendar_service``         — blackout gate.

Every component is async, every component is replay-safe (passes
``as_of_ts`` through to the underlying services). Errors degrade
gracefully: a single failed pillar simply contributes 50 (neutral)
to the composite rather than blowing up the whole call.

Public surface:

    score_symbol(symbol, as_of_ts=None, bars=None) -> AlphaScore
    score_universe(symbols, as_of_ts=None)         -> dict[str, AlphaScore]

The agent is *stateless*; results are not cached. Callers wanting
per-tick caching should layer their own memo around this.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Iterable

import pandas as pd

from models.alpha_score import (
    WEIGHTS,
    AlphaScore,
    SubScore,
)
from services.economic_calendar_service import in_event_blackout
from services.macro_pulse_service import compute_macro_pulse, intermarket_score_0_100
from services.news_sentiment_engine import (
    compute_sentiment_multiplier,
    sentiment_score_0_100,
)
from services.relative_strength_service import (
    compute_relative_strength,
    price_action_score_0_100,
)
from services.volume_profile_service import build_profile, volume_profile_score_0_100

log = logging.getLogger(__name__)


# Bucket thresholds — these are the same numbers the expectancy report
# uses to split high vs low alpha trades. Keep aligned.
HIGH_THRESHOLD = 80.0
MEDIUM_THRESHOLD = 50.0


def _bucket_for(score: float) -> str:
    if score >= HIGH_THRESHOLD:
        return "high"
    if score >= MEDIUM_THRESHOLD:
        return "medium"
    return "low"


async def _safe_call(label: str, coro):
    """Run a coroutine, return its result or None on any error."""
    try:
        return await coro
    except Exception as e:                         # noqa: BLE001
        log.warning("alpha_score: %s failed: %s", label, e)
        return None


async def score_symbol(
    symbol: str,
    *,
    as_of_ts: datetime | None = None,
    benchmark: str = "SPY",
    macro_pulse=None,
) -> AlphaScore:
    """Score a single symbol. ``macro_pulse`` may be passed pre-computed
    (so a universe loop computes it once instead of N times)."""
    from services.data_service import get_bars  # lazy: avoids yfinance at import
    as_of = as_of_ts or datetime.now(timezone.utc)

    # Pre-fetch shared macro pulse once if not provided.
    if macro_pulse is None:
        macro_pulse = await _safe_call("macro_pulse", compute_macro_pulse(as_of))

    # Run the per-symbol calls in parallel for throughput.
    rs_task = asyncio.create_task(
        compute_relative_strength(symbol, benchmark=benchmark, as_of_ts=pd.Timestamp(as_of))
    )
    sent_task = asyncio.create_task(
        compute_sentiment_multiplier(symbol, as_of_ts=as_of)
    )
    bars_task = asyncio.create_task(_safe_call(
        f"bars/{symbol}",
        get_bars(symbol, "1d", as_of_ts=pd.Timestamp(as_of), min_bars=40),
    ))

    rs = await _safe_call("rs", rs_task)
    sent = await _safe_call("sentiment", sent_task)
    bars = await bars_task

    sub_scores: dict[str, SubScore] = {}

    # ── Price action / VCP ────────────────────────────────────────────────
    if rs is not None:
        pa_score, pa_rationale = price_action_score_0_100(rs)
    else:
        pa_score, pa_rationale = 50.0, "rs_unavailable"
    sub_scores["price_action"] = SubScore(
        name="price_action",
        score=pa_score,
        rationale=pa_rationale,
        raw=rs.model_dump() if rs is not None else {},
    )

    # ── Intermarket ───────────────────────────────────────────────────────
    if macro_pulse is not None:
        im_score, im_rationale = intermarket_score_0_100(macro_pulse)
    else:
        im_score, im_rationale = 50.0, "macro_pulse_unavailable"
    sub_scores["intermarket"] = SubScore(
        name="intermarket",
        score=im_score,
        rationale=im_rationale,
        raw=macro_pulse.model_dump(mode="json") if macro_pulse is not None else {},
    )

    # ── Volume profile ────────────────────────────────────────────────────
    if bars is not None and not bars.empty:
        try:
            vp = build_profile(symbol, bars.tail(60), bins=40)
            vp_score, vp_rationale = volume_profile_score_0_100(vp)
            vp_raw = vp.model_dump()
        except Exception as e:                     # noqa: BLE001
            log.warning("alpha_score: VP build failed for %s: %s", symbol, e)
            vp_score, vp_rationale, vp_raw = 50.0, f"vp_failed:{e}", {}
    else:
        vp_score, vp_rationale, vp_raw = 50.0, "bars_unavailable", {}
    sub_scores["volume_profile"] = SubScore(
        name="volume_profile",
        score=vp_score,
        rationale=vp_rationale,
        raw=vp_raw,
    )

    # ── Sentiment ─────────────────────────────────────────────────────────
    if sent is not None:
        s_score = sentiment_score_0_100(sent)
        sub_scores["sentiment"] = SubScore(
            name="sentiment",
            score=s_score,
            rationale=sent.rationale,
            raw=sent.model_dump(mode="json"),
        )
        sentiment_multiplier = sent.multiplier
        sentiment_tags = list(sent.tags)
    else:
        sub_scores["sentiment"] = SubScore(
            name="sentiment", score=50.0, rationale="no_data", raw={},
        )
        sentiment_multiplier = 1.0
        sentiment_tags = []

    composite = sum(
        sub_scores[name].score * WEIGHTS[name]
        for name in WEIGHTS
    )

    # The sentiment multiplier scales the composite around its midpoint
    # rather than overpowering it: a 1.2x multiplier on a 70 score becomes
    # 50 + (70-50)*1.2 = 74, not 84. This is intentional — sentiment is
    # the smallest-weighted pillar, but the multiplier provides additional
    # asymmetric upside on confirmed-positive narratives.
    adjusted = 50 + (composite - 50) * sentiment_multiplier
    adjusted = max(0.0, min(100.0, adjusted))

    blocked = False
    block_reasons: list[str] = []
    in_blackout, upcoming = in_event_blackout(as_of, hours_before=24)
    if in_blackout:
        blocked = True
        upcoming_names = ", ".join(f"{e.name}@{e.scheduled_at.isoformat()}" for e in upcoming[:3])
        block_reasons.append(f"event_blackout: {upcoming_names}")

    return AlphaScore(
        symbol=symbol,
        as_of_ts=as_of,
        sub_scores=sub_scores,
        weights=dict(WEIGHTS),
        composite=round(composite, 2),
        sentiment_multiplier=sentiment_multiplier,
        adjusted_composite=round(adjusted, 2),
        bucket=_bucket_for(adjusted),
        blocked=blocked,
        block_reasons=block_reasons,
        tags=sentiment_tags,
    )


async def score_universe(
    symbols: Iterable[str],
    *,
    as_of_ts: datetime | None = None,
    benchmark: str = "SPY",
    concurrency: int = 8,
) -> dict[str, AlphaScore]:
    """Score a list of symbols in parallel, sharing the macro pulse.

    Designed for hundreds of symbols: macro pulse + FRED hits happen
    once; per-symbol work runs through an asyncio.Semaphore so we don't
    saturate yfinance.
    """
    syms = [s.upper() for s in symbols]
    as_of = as_of_ts or datetime.now(timezone.utc)
    macro_pulse = await _safe_call("macro_pulse", compute_macro_pulse(as_of))
    sem = asyncio.Semaphore(concurrency)

    async def _worker(sym: str) -> tuple[str, AlphaScore | None]:
        async with sem:
            try:
                score = await score_symbol(
                    sym, as_of_ts=as_of, benchmark=benchmark, macro_pulse=macro_pulse,
                )
                return sym, score
            except Exception as e:                 # noqa: BLE001
                log.warning("score_universe: %s failed: %s", sym, e)
                return sym, None

    results = await asyncio.gather(*(_worker(s) for s in syms))
    return {sym: score for sym, score in results if score is not None}
