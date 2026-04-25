"""trade_lookup.py — unified "trade by id" lookup across storage backends.

A trade lives in one of two places depending on its lifecycle stage:

  pending_approvals (SQLite)  — TradePlan awaiting ack, approved & awaiting
                                 fill, or filled and open. Indexed by plan_id.
  trade_logs/*.jsonl          — TradeRecord written when the trade closes.
                                 Indexed by trade_id.

The trade detail page (and clickable rows from the dashboard) needs one
``GET /trades/{id}`` route that handles both. This module abstracts the
two backends behind a single ``get(id) -> TradeView | None`` so the
router doesn't care which type the caller gave it.

A ``TradeView`` is a thin wrapper that exposes the same field names
regardless of source — `symbol`, `direction`, `strategy_name`,
`entry_price`, `stop_price`, etc. Callers that want the raw underlying
object can read ``view.raw``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from models import TradeRecord
from services import db_service, log_service

logger = logging.getLogger(__name__)


TradeStage = Literal[
    "pending",            # awaiting human ack
    "approved",           # acked, order placed, awaiting fill
    "open",               # filled, position live
    "closed",             # exited, TradeRecord written
    "rejected",           # blocked by gates or human reject
    "expired",            # ack window passed
    "unknown",
]


# --------------------------------------------------------------------------- #
# Unified view
# --------------------------------------------------------------------------- #


@dataclass
class TradeView:
    """Storage-agnostic projection of a trade for the detail page."""

    id: str                              # plan_id or trade_id
    source: Literal["pending", "jsonl"]  # which backend it came from
    stage: TradeStage

    # Core fields surfaced by the UI — None when unavailable
    symbol: str
    direction: str | None        = None  # "long" | "short"
    strategy_name: str | None    = None
    mode: str | None             = None  # research | paper | live
    ts_created: str | None       = None
    ts_entered: str | None       = None
    ts_exited: str | None        = None

    entry_price: float | None    = None
    stop_price: float | None     = None
    tp1_price: float | None      = None
    tp2_price: float | None      = None
    position_size: int | None    = None
    position_risk_usd: float | None = None

    # Outcome (closed only)
    pnl_pct: float | None        = None
    pnl_usd: float | None        = None
    pnl_r: float | None          = None
    win: bool | None             = None
    exit_reason: str | None      = None
    mfe_pct: float | None        = None
    mae_pct: float | None        = None

    # Carry-throughs for the detail page
    thesis: dict[str, Any]       = field(default_factory=dict)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    setup: dict[str, Any]        = field(default_factory=dict)
    raw: Any                     = None  # original dict / TradeRecord

    @property
    def is_active(self) -> bool:
        """True if the trade can still be edited (pending / approved / open)."""
        return self.stage in {"pending", "approved", "open"}

    @property
    def is_closed(self) -> bool:
        return self.stage == "closed"


# --------------------------------------------------------------------------- #
# Lookup
# --------------------------------------------------------------------------- #


async def get(trade_id: str) -> TradeView | None:
    """Find a trade by id across both backends. SQLite first, JSONL fallback."""
    plan = await db_service.get_plan_by_id(trade_id)
    if plan is not None:
        return _view_from_plan(plan)
    rec = await _find_trade_record(trade_id)
    if rec is not None:
        return _view_from_record(rec)
    return None


# --------------------------------------------------------------------------- #
# Adapters — pending_approvals row → TradeView
# --------------------------------------------------------------------------- #


def _view_from_plan(plan: dict[str, Any]) -> TradeView:
    """Build a TradeView from a pending_approvals row + its TradePlan JSON.

    The DB stores the full TradePlan as JSON in ``plan_json``; we read
    nested fields out of it for a stable surface even as TradePlan
    grows new fields.
    """
    import json

    plan_obj = {}
    raw = plan.get("plan_json")
    if isinstance(raw, str):
        try:
            plan_obj = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("trade_lookup: bad plan_json for %s", plan.get("plan_id"))

    setup = plan_obj.get("setup", {}) or {}
    entry = (setup.get("entry") or {})
    stop  = (setup.get("stop_loss", {}) or {}).get("initial", {}) or {}
    tps   = setup.get("take_profit") or []
    risk  = plan_obj.get("risk", {}) or {}
    instr = plan_obj.get("instrument", {}) or {}
    thesis = plan_obj.get("thesis", {}) or {}

    stage = _stage_from_status(plan.get("status", ""))
    return TradeView(
        id=plan.get("plan_id", ""),
        source="pending",
        stage=stage,
        symbol=instr.get("symbol", plan.get("symbol", "")),
        direction=setup.get("direction"),
        strategy_name=_strategy_from_thesis(thesis),
        mode=plan_obj.get("mode"),
        ts_created=plan.get("ts_created") or plan_obj.get("ts_created"),
        entry_price=_f(entry.get("price")),
        stop_price=_f(stop.get("price")),
        tp1_price=_f(tps[0]["price"]) if len(tps) >= 1 and "price" in tps[0] else None,
        tp2_price=_f(tps[1]["price"]) if len(tps) >= 2 and "price" in tps[1] else None,
        position_size=int(risk["position_size_shares"]) if risk.get("position_size_shares") else None,
        position_risk_usd=_f(risk.get("position_risk_usd")),
        thesis=thesis,
        evidence=plan_obj.get("evidence") or [],
        setup=setup,
        raw=plan_obj,
    )


def _stage_from_status(status: str) -> TradeStage:
    s = (status or "").lower()
    if s in ("pending", "awaiting_ack"):     return "pending"
    if s in ("approved", "awaiting_fill"):   return "approved"
    if s in ("filled", "open"):              return "open"
    if s in ("rejected",):                   return "rejected"
    if s in ("expired",):                    return "expired"
    if s in ("closed",):                     return "closed"
    return "unknown"


def _strategy_from_thesis(thesis: dict) -> str | None:
    """Extract strategy_name. Stored under thesis.strategy or in the
    summary; for now we look in a couple of likely places."""
    if not thesis:
        return None
    for k in ("strategy", "strategy_name", "summary"):
        v = thesis.get(k)
        if isinstance(v, str) and v:
            # `summary` is freeform — only use if no dedicated key exists
            if k != "summary":
                return v
    # Fallback: first contributing pattern name
    pats = thesis.get("patterns") or thesis.get("signal_ids") or []
    if isinstance(pats, list) and pats:
        return str(pats[0])
    return None


# --------------------------------------------------------------------------- #
# Adapters — TradeRecord (JSONL) → TradeView
# --------------------------------------------------------------------------- #


async def _find_trade_record(trade_id: str) -> TradeRecord | None:
    """Scan JSONL months newest-first for a matching trade_id.

    Single-user scale — full scan is fine. Optimize later (e.g. SQLite
    index of trade_id → file:line) when JSONL has tens of thousands of
    rows. Hot path is the pending_approvals branch anyway; closed-trade
    detail views are infrequent.
    """
    months = await log_service.list_months()
    for ym in reversed(months):
        for rec in await log_service.read_records(ym):
            if rec.trade_id == trade_id:
                return rec
    return None


def _view_from_record(rec: TradeRecord) -> TradeView:
    inst    = rec.instrument or {}
    setup   = rec.setup_snapshot or {}
    exec_   = rec.execution or {}
    out     = rec.outcome or {}
    life    = rec.lifecycle or {}

    return TradeView(
        id=rec.trade_id,
        source="jsonl",
        stage="closed",
        symbol=inst.get("symbol", ""),
        direction=setup.get("direction"),
        strategy_name=setup.get("strategy_name"),
        mode=rec.mode,
        ts_created=life.get("ts_planned"),
        ts_entered=life.get("ts_entered"),
        ts_exited=life.get("ts_exited_last"),
        entry_price=_f(exec_.get("entry_price_actual") or exec_.get("entry_price_planned")),
        stop_price=_f(setup.get("stop_price_planned")),
        tp1_price=_f(setup.get("tp1_price_planned")),
        tp2_price=_f(setup.get("tp2_price_planned")),
        position_size=_i(exec_.get("filled_shares")),
        position_risk_usd=_f(exec_.get("planned_risk_usd")),
        pnl_pct=_f(out.get("pnl_pct")),
        pnl_usd=_f(out.get("pnl_usd")),
        pnl_r=_f(out.get("pnl_r_multiple")),
        win=out.get("win"),
        exit_reason=out.get("exit_reason"),
        mfe_pct=_f(out.get("mfe")),
        mae_pct=_f(out.get("mae")),
        thesis={"summary": setup.get("market_context")} if setup.get("market_context") else {},
        evidence=[],
        setup=setup,
        raw=rec,
    )


# --------------------------------------------------------------------------- #
# Internal coercion helpers
# --------------------------------------------------------------------------- #


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _i(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
