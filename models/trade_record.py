"""TradeRecord — JSONL log schema. Field names FROZEN at v1.0.0.

DO NOT change field names after first write to JSONL — they are the ML feature
contract. New fields may be added; existing names must never be renamed or
removed without bumping schema_version and writing a migration.

Inner block shapes (lifecycle, setup_snapshot, execution, outcome, postmortem)
are documented in SKILL.md §7. They are kept as `dict` here to allow incremental
ML feature additions without churning this file.
"""
from typing import Literal

from pydantic import BaseModel


class TradeRecord(BaseModel):
    trade_id: str
    plan_id: str
    schema_version: str = "1.0.0"
    mode: Literal["research", "paper", "live"]
    broker: str
    instrument: dict
    lifecycle: dict
    setup_snapshot: dict
    execution: dict
    outcome: dict
    postmortem: dict
