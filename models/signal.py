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
    timeframe: Timeframe
    key_levels: KeyLevels
    evidence: list[Evidence] = []
    invalidation_condition: str
    sentiment: SentimentBlock | None = None
