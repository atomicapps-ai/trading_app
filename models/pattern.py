"""PatternResult — the output of every pattern detector.

Shape is stable across all 9 detectors so the analyst can aggregate
them uniformly. A detector returns None when the pattern isn't present;
otherwise it fills in entry / stop / target prices, PQS math, and
evidence items that the UI displays to the human approver.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PatternResult(BaseModel):
    pattern_name: str
    detected: bool = True
    direction: Literal["long", "short"]

    # Pattern Quality Score breakdown
    pqs_base: int
    pqs_modifiers: dict[str, int] = Field(default_factory=dict)
    pqs_total: int  # capped at 100 by the caller

    # Price levels
    entry_price: float
    stop_price: float
    tp1_price: float
    tp2_price: float
    invalidation_level: float
    invalidation_condition: str

    # Evidence — displayed to the human in the pending approval view
    evidence_items: list[dict] = Field(default_factory=list)

    # Watchlist — pattern partially formed, doesn't emit a signal yet
    watchlist_candidate: bool = False
    unmet_conditions: list[str] = Field(default_factory=list)
