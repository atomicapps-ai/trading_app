"""alpha_score.py — data models for the quant + sentiment Alpha Score.

The Alpha Score blends four orthogonal signals (technical / intermarket /
volume profile / news) into a single 0-100 conviction number that gates
trade execution. Models here are pure data containers; the math lives in
``agents/alpha_score_agent.py``.

All sub-scores are normalized to [0, 100]. The weighted total is also
[0, 100]. Higher = stronger long bias; lower = avoid / consider short.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


WEIGHTS: dict[str, float] = {
    "price_action": 0.40,
    "intermarket": 0.25,
    "volume_profile": 0.20,
    "sentiment": 0.15,
}


class SentimentMultiplier(BaseModel):
    """Sentiment-derived multiplier applied to a base technical signal.

    The multiplier shifts position size or final score (capped) depending
    on news polarity. Defaults reflect the user spec: +1.2 for positive
    earnings surprise, -0.5 for regulatory headwinds.
    """

    symbol: str
    as_of_ts: datetime
    avg_compound: float = 0.0
    n_articles: int = 0
    multiplier: float = 1.0
    tags: list[str] = Field(default_factory=list)
    rationale: str = ""

    @field_validator("multiplier")
    @classmethod
    def _clamp_multiplier(cls, v: float) -> float:
        return max(0.1, min(2.0, float(v)))


class EconomicEvent(BaseModel):
    """A high-impact macro release (FOMC, CPI, NFP, GDP, PCE, ...)."""

    name: str
    category: Literal["FOMC", "CPI", "NFP", "PCE", "GDP", "RETAIL", "OTHER"]
    scheduled_at: datetime
    importance: Literal["high", "medium", "low"] = "high"
    notes: str | None = None


class MacroPulse(BaseModel):
    """Snapshot of intermarket signals used by the alpha score."""

    as_of_ts: datetime
    yield_2y: float | None = None
    yield_10y: float | None = None
    yield_curve_2s10s: float | None = None  # 10Y minus 2Y
    yield_curve_regime: Literal[
        "inverted_deep", "inverted", "flat", "normal", "steep", "unknown"
    ] = "unknown"
    yield_curve_change_5d: float | None = None
    dxy_level: float | None = None
    dxy_change_5d: float | None = None
    dxy_regime: Literal["weak", "neutral", "strong", "unknown"] = "unknown"
    nikkei_overnight_pct: float | None = None
    dax_overnight_pct: float | None = None
    spy_gap_risk: Literal["bullish", "bearish", "neutral", "unknown"] = "unknown"
    fed_funds_rate: float | None = None
    notes: list[str] = Field(default_factory=list)


class VolumeProfile(BaseModel):
    """Volume Profile (VPVR) snapshot for one symbol over a lookback window."""

    symbol: str
    lookback_bars: int
    poc_price: float
    value_area_high: float  # VAH
    value_area_low: float   # VAL
    current_price: float
    distance_to_poc_pct: float
    in_value_area: bool
    location: Literal["above_vah", "in_value_area", "below_val", "at_poc"]


class RelativeStrength(BaseModel):
    """Symbol RS vs benchmark + VCP qualification flag."""

    symbol: str
    benchmark: str = "SPY"
    rs_20d: float = 0.0  # symbol pct return − benchmark pct return, 20d
    rs_60d: float = 0.0
    benchmark_pulling_back: bool = False
    vcp_qualified: bool = False
    contraction_count: int = 0
    latest_range_pct: float | None = None


class SubScore(BaseModel):
    """One pillar of the alpha score, with its raw value, normalized score, and rationale."""

    name: Literal["price_action", "intermarket", "volume_profile", "sentiment"]
    raw: dict[str, Any] = Field(default_factory=dict)
    score: float = 0.0  # 0-100
    rationale: str = ""

    @field_validator("score")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(0.0, min(100.0, float(v)))


class AlphaScore(BaseModel):
    """Final weighted composite score for a single (symbol, as_of_ts)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    symbol: str
    as_of_ts: datetime
    direction: Literal["long", "short", "flat"] = "long"
    sub_scores: dict[str, SubScore] = Field(default_factory=dict)
    weights: dict[str, float] = Field(default_factory=lambda: dict(WEIGHTS))
    composite: float = 0.0  # 0-100
    sentiment_multiplier: float = 1.0
    adjusted_composite: float = 0.0
    bucket: Literal["high", "medium", "low"] = "low"
    blocked: bool = False
    block_reasons: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @field_validator("composite", "adjusted_composite")
    @classmethod
    def _clamp_score(cls, v: float) -> float:
        return max(0.0, min(100.0, float(v)))

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class BacktestTrade(BaseModel):
    """One backtested trade row consumed by expectancy aggregation."""

    symbol: str
    entry_ts: datetime
    exit_ts: datetime
    direction: Literal["long", "short"] = "long"
    entry_price: float
    exit_price: float
    alpha_score: float
    bucket: Literal["high", "medium", "low"]
    sentiment_multiplier: float = 1.0
    tags: list[str] = Field(default_factory=list)
    pnl_pct: float = 0.0
    pnl_r: float = 0.0
    holding_bars: int = 0
    win: bool = False


class ExpectancyReport(BaseModel):
    """Output of the expectancy analysis comparing high/medium/low alpha buckets."""

    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    universe_size: int = 0
    trades_total: int = 0
    by_bucket: dict[str, dict[str, float]] = Field(default_factory=dict)
    tag_correlations: list[dict[str, Any]] = Field(default_factory=list)
    weights_used: dict[str, float] = Field(default_factory=lambda: dict(WEIGHTS))
    notes: list[str] = Field(default_factory=list)
