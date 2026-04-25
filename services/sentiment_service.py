"""sentiment_service.py — VADER sentiment scoring for news items.

VADER (Valence Aware Dictionary and sEntiment Reasoner) is a rule-based,
lexicon-driven sentiment analyzer tuned for short social-media-style
text. It performs surprisingly well on financial headlines despite not
being domain-specific — a reasonable v1 baseline before we layer in
finance-specific scoring.

Why scoring lives outside news_service
--------------------------------------
- ``news_service`` writes a JSONL cache that's already in the wild;
  embedding sentiment in NewsItem would force a re-cache.
- VADER is fast (~0.1ms per headline). Scoring on read is fine.
- Keeping concerns separate means we can swap VADER for a finance-tuned
  model later without touching news_service.

API
---
    score_text(text)        -> SentimentScore
    score_items(items)      -> list[ScoredNewsItem]
    summarize(items)        -> AggregateSentiment

The analyzer is lazy-initialized on first use so importing this module
is cheap (the VADER lexicon load takes ~50ms).
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from services.news_service import NewsItem

logger = logging.getLogger(__name__)

_analyzer = None  # lazy: vaderSentiment.SentimentIntensityAnalyzer instance


def _get_analyzer():
    global _analyzer
    if _analyzer is None:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        _analyzer = SentimentIntensityAnalyzer()
    return _analyzer


# --------------------------------------------------------------------------- #
# Data classes
# --------------------------------------------------------------------------- #


@dataclass
class SentimentScore:
    """VADER's four scores + a categorical label.

    compound  — single number in [-1, 1]; the headline figure.
    pos / neu / neg — proportions in [0, 1] summing to 1.
    label     — categorical bucket on compound:
                very_positive >= 0.5
                positive      >= 0.05
                neutral       (-0.05, 0.05)
                negative      <= -0.05
                very_negative <= -0.5
    """
    compound: float
    pos: float
    neu: float
    neg: float
    label: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScoredNewsItem:
    """A NewsItem zipped with its sentiment score.

    Avoids re-importing pydantic models in callers — we just hand back
    a flat dict-friendly structure with the article fields they need.
    """
    headline: str
    url: str
    source: str
    published_at: str        # iso8601 string for JSON serialization
    author: str | None
    article_id: str
    sentiment: SentimentScore

    def to_dict(self) -> dict[str, Any]:
        return {
            "headline": self.headline,
            "url": self.url,
            "source": self.source,
            "published_at": self.published_at,
            "author": self.author,
            "article_id": self.article_id,
            "sentiment": self.sentiment.to_dict(),
        }


@dataclass
class AggregateSentiment:
    """Summary across a batch of news items."""
    n: int                          = 0
    avg_compound: float | None      = None
    label: str                      = "n/a"   # bucket of avg_compound
    counts: dict[str, int]          = field(default_factory=dict)   # label -> n
    most_positive: ScoredNewsItem | None = None
    most_negative: ScoredNewsItem | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "avg_compound": self.avg_compound,
            "label": self.label,
            "counts": self.counts,
            "most_positive": self.most_positive.to_dict() if self.most_positive else None,
            "most_negative": self.most_negative.to_dict() if self.most_negative else None,
        }


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #


def _label_for(compound: float) -> str:
    if compound >=  0.50: return "very_positive"
    if compound >=  0.05: return "positive"
    if compound <= -0.50: return "very_negative"
    if compound <= -0.05: return "negative"
    return "neutral"


def score_text(text: str) -> SentimentScore:
    """Run VADER on a single text. Empty / None input → neutral score."""
    if not text or not text.strip():
        return SentimentScore(compound=0.0, pos=0.0, neu=1.0, neg=0.0, label="neutral")
    try:
        s = _get_analyzer().polarity_scores(text)
    except Exception as e:                                    # noqa: BLE001
        logger.warning("VADER scoring failed: %s", e)
        return SentimentScore(compound=0.0, pos=0.0, neu=1.0, neg=0.0, label="neutral")
    compound = round(float(s["compound"]), 3)
    return SentimentScore(
        compound=compound,
        pos=round(float(s["pos"]), 3),
        neu=round(float(s["neu"]), 3),
        neg=round(float(s["neg"]), 3),
        label=_label_for(compound),
    )


def score_news_item(item: "NewsItem") -> SentimentScore:
    """Score a NewsItem — combines headline and body when both are present.

    VADER works fine on headlines alone; including body adds nuance for
    longer articles but is optional. We use ``headline + ' ' + body``
    when body exists, else just the headline.
    """
    text = item.headline if not item.body else f"{item.headline}. {item.body}"
    return score_text(text)


def score_items(items: list["NewsItem"]) -> list[ScoredNewsItem]:
    out: list[ScoredNewsItem] = []
    for it in items:
        s = score_news_item(it)
        out.append(ScoredNewsItem(
            headline=it.headline,
            url=it.url,
            source=it.source,
            published_at=it.published_at.isoformat(),
            author=it.author,
            article_id=it.article_id,
            sentiment=s,
        ))
    return out


def summarize(items: list["NewsItem"]) -> AggregateSentiment:
    """Aggregate sentiment across a batch of articles.

    Provides: count by label, average compound, single most-positive
    and most-negative items (for the trade detail card highlights).
    """
    if not items:
        return AggregateSentiment()

    scored = score_items(items)
    counts: dict[str, int] = {}
    for sc in scored:
        counts[sc.sentiment.label] = counts.get(sc.sentiment.label, 0) + 1

    avg = sum(sc.sentiment.compound for sc in scored) / len(scored)
    avg = round(avg, 3)
    most_pos = max(scored, key=lambda s: s.sentiment.compound)
    most_neg = min(scored, key=lambda s: s.sentiment.compound)

    return AggregateSentiment(
        n=len(scored),
        avg_compound=avg,
        label=_label_for(avg),
        counts=counts,
        most_positive=most_pos if most_pos.sentiment.compound > 0 else None,
        most_negative=most_neg if most_neg.sentiment.compound < 0 else None,
    )
