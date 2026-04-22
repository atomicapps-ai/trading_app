"""ExecutionResult — what the executioner returns to the caller.

Populated on every execute_plan() call: successful placements, broker
rejections, and internal safety-gate refusals all produce this object.
The pending router persists it into pending_approvals so the UI and
trade log can see exactly what happened.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ExecutionResult(BaseModel):
    plan_id: str
    ack_id: str
    placed: bool
    ts: str

    # Present on successful placements
    client_order_id: str | None = None
    broker_order_id: str | None = None
    broker_name: str | None = None
    order_json: dict | None = None
    order_ack_json: dict | None = None

    # Present on rejection (either executioner gate or broker reject)
    reject_reason: str | None = None
