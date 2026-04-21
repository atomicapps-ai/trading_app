"""Compliance and risk verdicts; human approval ack."""
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

ComplianceGate = Literal["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"]
RiskGate = Literal["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9"]


class ComplianceVerdict(BaseModel):
    verdict_id: str = Field(default_factory=lambda: str(uuid4()))
    plan_id: str
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    result: Literal["pass", "block"]
    gates_evaluated: list[ComplianceGate]
    gates_failed: list[ComplianceGate] = []
    block_reason: str | None = None
    cited_rule: str | None = None


class RiskVerdict(BaseModel):
    verdict_id: str = Field(default_factory=lambda: str(uuid4()))
    plan_id: str
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    result: Literal["approve", "resize", "reject"]
    original_size_shares: int
    approved_size_shares: int
    gates_evaluated: list[RiskGate]
    gates_triggered: list[RiskGate] = []
    resize_reason: str | None = None
    reject_reason: str | None = None
    approved_risk_usd: float = 0.0
    approved_notional_usd: float = 0.0


class HumanAckRecord(BaseModel):
    ack_id: str = Field(default_factory=lambda: str(uuid4()))
    plan_id: str
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    action: Literal["approve", "reject", "modify"]
    modified_fields: dict = {}
    ack_by: str = "human"
