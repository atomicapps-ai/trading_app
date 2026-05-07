"""news_sentiment_engine.py — narrative layer for the Alpha Score.

Wraps the existing ``services/sentiment_service`` (VADER) with two
domain-specific extensions the user spec requires:

1. **News-tag classifier.** A regex pack over headline + body that
   labels articles with tradable tags such as ``earnings_beat``,
   ``regulatory_headwind``, ``ai_integration``, ``share_buyback``.
   The same tags later feed the optimizer's correlation analysis
   ("which tags correlate with post-VCP breakout success").

2. **Sentiment multiplier.** A per-symbol scalar derived from the
   tag mix and aggregate VADER score. The defaults match the spec:
   +1.2 for an earnings beat, -0.5 for a regulatory headwind, with
   pure VADER nudging the rest of the [0.5, 1.5] range.

Both functions are pure async wrappers around the news cache, so they
inherit the cache's ``as_of_ts`` semantics — safe to call from
backtest replay loops.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from models.alpha_score import SentimentMultiplier
from services.sentiment_service import score_news_item, summarize

if TYPE_CHECKING:
    from services.news_service import NewsItem

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# News tag taxonomy
# --------------------------------------------------------------------------- #
#
# Each tag is (label, pattern, polarity). Polarity is the multiplier
# delta the tag contributes when present. A single article can carry
# multiple tags; we sum the deltas (clamped) to form the multiplier.

TAG_RULES: list[tuple[str, re.Pattern[str], float]] = [
    # Earnings
    ("earnings_beat",        re.compile(r"\b(beat|beats|exceeds?|tops?|surpass(es)?|crush(es|ed)?) (analyst|consensus|estimate|expectation|forecast)", re.I), +0.20),
    ("earnings_raise",       re.compile(r"\b(rais(es|ed)|hik(es|ed)|boost(s|ed)?|lift(s|ed)?) (full[- ]year )?(guidance|forecast|outlook)", re.I), +0.20),
    ("earnings_miss",        re.compile(r"\b(miss(es|ed)?|below|short of|fail(s|ed) to (meet|beat)) (analyst|consensus|estimate|expectation)", re.I), -0.30),
    ("earnings_cut",         re.compile(r"\b(cut(s|ting)?|lower(s|ed)?|slash(es|ed)?|trim(s|med)?) (full[- ]year )?(guidance|forecast|outlook)", re.I), -0.30),

    # Regulatory / legal
    ("regulatory_headwind",  re.compile(r"\b(probe|investigation|antitrust|subpoena|fined?|penal(ty|ize)|lawsuit|class[- ]action|sec charge|doj charge|recall)\b", re.I), -0.50),
    ("regulatory_tailwind",  re.compile(r"\b(approval|approves?|cleared|authoriz(es|ed)|fda (approves|clears))\b", re.I), +0.20),

    # Capital allocation
    ("share_buyback",        re.compile(r"\b(buy[- ]?back|repurchase program|stock repurchase)\b", re.I), +0.15),
    ("dividend_increase",    re.compile(r"\b(rais(es|ed)|increas(es|ed)|hik(es|ed)) (the )?(quarterly )?dividend\b", re.I), +0.10),
    ("dividend_cut",         re.compile(r"\b(cut(s|ting)?|suspend(s|ed)?|reduc(es|ed)) (the )?(quarterly )?dividend\b", re.I), -0.20),

    # Strategic / product
    ("ai_integration",       re.compile(r"\b(generative ai|llm|large language model|ai[- ](integration|partnership|adoption|powered)|nvidia (gpu|chip)s?)\b", re.I), +0.15),
    ("acquisition_target",   re.compile(r"\b(takeover bid|acquisition target|to (be )?acquir(e|ed)|buyout offer)\b", re.I), +0.30),
    ("acquisition_buyer",    re.compile(r"\b(acquir(es|ed)|to acquire|will acquire|agreed to (purchase|acquire))\b", re.I), -0.05),
    ("partnership",          re.compile(r"\b(strategic partnership|collaboration agreement|joint venture)\b", re.I), +0.05),

    # Operations / labor
    ("layoffs",              re.compile(r"\b(lay[- ]?off(s|ing)?|workforce reduction|cut(s|ting)? \d+%? (of )?(staff|workforce|jobs))\b", re.I), -0.05),
    ("ceo_change",           re.compile(r"\b(ceo (steps? down|resigns?|departs?|fired|named|appointed)|new (chief executive|ceo))\b", re.I), -0.05),

    # Demand / forecast
    ("demand_strength",      re.compile(r"\b(record (sales|demand|revenue|orders)|strong (demand|backlog|orders))\b", re.I), +0.10),
    ("demand_weakness",      re.compile(r"\b(weak (demand|sales)|soft(ening)? demand|order book (shrink|decline)|inventory build)\b", re.I), -0.10),

    # Analyst actions
    ("analyst_upgrade",      re.compile(r"\b(upgrad(es|ed)\b[^.]{0,40}\b(to (buy|outperform|overweight|strong buy)|price target)|price target rais(es|ed))", re.I), +0.10),
    ("analyst_downgrade",    re.compile(r"\b(downgrad(es|ed)\b[^.]{0,40}\b(to (sell|underperform|underweight)|price target)|price target (cut|lower(ed)?))", re.I), -0.10),
]


def classify_tags(text: str) -> list[str]:
    """Return the list of tag labels matching the given text."""
    if not text:
        return []
    return [label for label, pat, _ in TAG_RULES if pat.search(text)]


def _polarity_for(tag: str) -> float:
    for label, _pat, delta in TAG_RULES:
        if label == tag:
            return delta
    return 0.0


def _vader_text(item: "NewsItem") -> str:
    return item.headline if not item.body else f"{item.headline}. {item.body}"


def aggregate_tags(items: list["NewsItem"]) -> dict[str, int]:
    """Count how many articles in the batch carry each tag."""
    counts: dict[str, int] = {}
    for it in items:
        for tag in set(classify_tags(_vader_text(it))):
            counts[tag] = counts.get(tag, 0) + 1
    return counts


def derive_multiplier(
    avg_compound: float,
    tag_counts: dict[str, int],
) -> tuple[float, str]:
    """Combine VADER's avg_compound and tag mix into a [0.1, 2.0] multiplier.

    Math: start at 1.0, add VADER drift (compound * 0.5, so [-0.5, +0.5]),
    add the polarity sum across present tags (each tag's delta, applied
    once even when tag fires on multiple articles — a single
    earnings-beat headline shouldn't compound 3x). Clamp at the end.
    """
    base = 1.0
    vader_drift = round(avg_compound * 0.5, 3)
    tag_drift = 0.0
    rationale_parts: list[str] = []

    for tag, count in tag_counts.items():
        delta = _polarity_for(tag)
        if delta == 0:
            continue
        tag_drift += delta
        rationale_parts.append(f"{tag}({count}):{delta:+.2f}")

    multiplier = base + vader_drift + tag_drift
    multiplier = max(0.1, min(2.0, multiplier))
    rationale = (
        f"vader_drift={vader_drift:+.3f}; "
        f"tags=[{', '.join(rationale_parts) if rationale_parts else 'none'}]; "
        f"final={multiplier:.3f}"
    )
    return round(multiplier, 3), rationale


async def compute_sentiment_multiplier(
    symbol: str,
    *,
    as_of_ts: datetime | None = None,
    lookback_days: int = 7,
) -> SentimentMultiplier:
    """Fetch recent news for ``symbol`` and return its sentiment multiplier.

    Pure of side-effects beyond the news cache. ``as_of_ts=None`` means
    "live now"; passing a historical timestamp makes the call backtest-safe.
    """
    from services.news_service import get_news  # lazy: avoids feedparser at import time
    end = as_of_ts or datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)

    try:
        items = await get_news(symbol, start=start, end=end)
    except Exception as e:                         # noqa: BLE001
        log.warning("compute_sentiment_multiplier: news fetch failed for %s: %s", symbol, e)
        items = []

    if not items:
        return SentimentMultiplier(
            symbol=symbol,
            as_of_ts=end,
            avg_compound=0.0,
            n_articles=0,
            multiplier=1.0,
            tags=[],
            rationale="no_articles_in_window",
        )

    aggregate = summarize(items)
    tag_counts = aggregate_tags(items)
    multiplier, rationale = derive_multiplier(aggregate.avg_compound or 0.0, tag_counts)

    return SentimentMultiplier(
        symbol=symbol,
        as_of_ts=end,
        avg_compound=aggregate.avg_compound or 0.0,
        n_articles=aggregate.n,
        multiplier=multiplier,
        tags=sorted(tag_counts.keys()),
        rationale=rationale,
    )


def sentiment_score_0_100(mult: SentimentMultiplier) -> float:
    """Map a SentimentMultiplier into the 0-100 sub-score space.

    Convention: multiplier 1.0 → score 50. Each 0.1 above/below 1.0
    moves the score by 10 points, capped at the [0, 100] band. We
    boost slightly when the article count is high (more conviction
    in the signal) and dampen when it's zero.
    """
    base = 50.0 + (mult.multiplier - 1.0) * 100.0
    if mult.n_articles == 0:
        return 50.0  # no information ≠ neutral signal; treat as neutral
    if mult.n_articles >= 10:
        # Pull a couple points further from neutral when the sample size is large.
        base = 50.0 + (base - 50.0) * 1.1
    return max(0.0, min(100.0, round(base, 1)))


def score_text_with_tags(text: str) -> dict[str, Any]:
    """Convenience helper for one-off scoring (e.g. earnings transcript line)."""
    from services.sentiment_service import score_text  # local: avoid extra deps
    sentiment = score_text(text)
    tags = classify_tags(text)
    return {
        "compound": sentiment.compound,
        "label": sentiment.label,
        "tags": tags,
        "tag_polarity_sum": round(sum(_polarity_for(t) for t in tags), 3),
    }
