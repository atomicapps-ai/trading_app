"""TradePlan — the central object passed through compliance, risk, executioner."""
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class EntryOrder(BaseModel):
    type: Literal["limit", "stop", "market_on_trigger"]
    price: float
    trigger_condition: str | None = None
    valid_until: str  # "session_close" | "gtc" | iso8601
    do_not_enter_windows: list[str] = []


class TakeProfitLeg(BaseModel):
    leg: int
    price: float
    size_pct: float
    reason: str


class StopLossInitial(BaseModel):
    type: Literal["hard", "stop_limit"]
    price: float
    reason: str


class TrailingStop(BaseModel):
    active: bool
    activate_after: str  # e.g. "price >= entry + 1.0R"
    mode: Literal["atr", "percent", "structural"]
    atr_multiple: float | None = None
    atr_period: int | None = None
    percent: float | None = None


class TimeStop(BaseModel):
    active: bool
    condition: str
    deadline: str  # iso8601


class ThesisInvalidation(BaseModel):
    active: bool
    condition: str


class StopLoss(BaseModel):
    initial: StopLossInitial
    trail: TrailingStop
    time_stop: TimeStop
    thesis_invalidation: ThesisInvalidation


class Setup(BaseModel):
    direction: Literal["long", "short"]
    entry: EntryOrder
    take_profit: list[TakeProfitLeg]
    stop_loss: StopLoss

    @field_validator("take_profit")
    @classmethod
    def tp_sums_to_100(cls, v: list[TakeProfitLeg]) -> list[TakeProfitLeg]:
        total = sum(leg.size_pct for leg in v)
        if abs(total - 100.0) > 1e-6:
            raise ValueError(
                f"take_profit size_pct must sum to 100; got {total}"
            )
        return v


class TradePlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    ts_created: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    mode: Literal["research", "paper", "live"]
    schema_version: str = "1.0.0"
    instrument: dict
    thesis: dict
    setup: Setup
    risk: dict
    execution: dict
    evidence: list[dict] = []
    tradingview_chart_url: str
