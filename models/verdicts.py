"""Compliance and risk verdicts; human approval ack.

Terminology (used everywhere — models, UI, API, tests):

    approved   — the gate let the plan through unchanged.
    resized    — risk-only; the gate approved with a reduced size.
    rejected   — the gate refused the plan.

Old terminology (``pass`` / ``block`` / ``approve`` / ``reject``) is
accepted as input for backward compatibility with any JSON that was
persisted under the earlier schema; a ``before``-mode validator
normalises it. New code should always emit the new values.
"""
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

ComplianceGate = Literal["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"]
RiskGate = Literal["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9"]

# Human-action vocabulary for the ack button stays ``approve`` / ``reject``
# — those are verbs describing what the human DID, not a gate outcome.
AckAction = Literal["approve", "reject", "modify"]

# Gate outcome vocabulary — what the gate SAID about the plan.
ComplianceResult = Literal["approved", "rejected"]
RiskResult = Literal["approved", "resized", "rejected"]

_COMPLIANCE_ALIAS = {"pass": "approved", "block": "rejected"}
_RISK_ALIAS = {"approve": "approved", "resize": "resized", "reject": "rejected"}


class ComplianceVerdict(BaseModel):
    verdict_id: str = Field(default_factory=lambda: str(uuid4()))
    plan_id: str
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    result: ComplianceResult
    gates_evaluated: list[ComplianceGate]
    gates_failed: list[ComplianceGate] = []
    block_reason: str | None = None
    cited_rule: str | None = None

    @field_validator("result", mode="before")
    @classmethod
    def _normalize_result(cls, v):
        return _COMPLIANCE_ALIAS.get(v, v)


class RiskVerdict(BaseModel):
    verdict_id: str = Field(default_factory=lambda: str(uuid4()))
    plan_id: str
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    result: RiskResult
    original_size_shares: int
    approved_size_shares: int
    gates_evaluated: list[RiskGate]
    gates_triggered: list[RiskGate] = []
    resize_reason: str | None = None
    reject_reason: str | None = None
    approved_risk_usd: float = 0.0
    approved_notional_usd: float = 0.0

    @field_validator("result", mode="before")
    @classmethod
    def _normalize_result(cls, v):
        return _RISK_ALIAS.get(v, v)


class HumanAckRecord(BaseModel):
    ack_id: str = Field(default_factory=lambda: str(uuid4()))
    plan_id: str
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    action: AckAction
    modified_fields: dict = {}
    ack_by: str = "human"
