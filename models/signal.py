"""Signal — emitted by analyst lenses, consumed by portfolio_manager."""
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

Lens = Literal["technical", "fundamental", "sentiment", "macro"]
Direction = Literal["long", "short", "neutral"]
Timeframe = Literal["intraday", "swing_days", "swing_weeks", "position"]
SourceTier = Literal["primary", "secondary", "tertiary"]
EventType = Literal[
    "earnings",
    "guidance",
    "m_a",
    "regulatory",
    "litigation",
    "macro",
    "insider_tx",
    "analyst_action",
]
Urgency = Literal["low", "medium", "high", "critical"]


class KeyLevels(BaseModel):
    support: float | None = None
    resistance: float | None = None
    invalidation: float


class Evidence(BaseModel):
    type: str
    ref: str


class SentimentBlock(BaseModel):
    score: float = Field(ge=-1.0, le=1.0)
    relevance_score: float = Field(ge=0.0, le=1.0)
    novelty_score: float = Field(ge=0.0, le=1.0)
    source_tier: SourceTier
    event_type: EventType


class Signal(BaseModel):
    signal_id: str = Field(default_factory=lambda: str(uuid4()))
    ts_emitted: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    symbol: str
    lens: Lens
    direction: Direction
    strength: float = Field(ge=0.0, le=1.0)
    # Uncapped pattern-quality score (pqs_base + modifiers). Unlike `strength`
    # (which is pqs_total/100 and saturates at 1.0 the moment a setup clears the
    # 100 cap), this keeps discriminating between "just clears" and "textbook",
    # so it drives the 1–5 setup-strength rating in the UI.
    pqs_raw: int | None = None
    timeframe: Timeframe
    key_levels: KeyLevels
    evidence: list[Evidence] = []
    invalidation_condition: str
    sentiment: SentimentBlock | None = None

    # Price suggestions from the source detector (technical lens sets these;
    # fundamental / sentiment lenses leave them None). portfolio_manager
    # picks the strongest signal with non-None prices as the plan's anchor.
    pattern_name: str | None = None
    entry_price: float | None = None
    stop_price: float | None = None
    tp1_price: float | None = None
    tp2_price: float | None = None
