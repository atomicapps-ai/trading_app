"""Pending-approvals router.

Reads live plans from SQLite via db_service. Each row carries both the
full TradePlan JSON and the compliance/risk verdicts, so the template
can render the decision context alongside the trade setup.

Ack flow
--------
POST /pending/{id}/ack with action:
  * approve → builds a HumanAckRecord, hands plan + verdicts + ack to
              the Executioner, which re-verifies every gate, translates
              the entry into an Order, and submits via the broker
              adapter. The ExecutionResult is persisted on the row.
  * reject  → flips status to 'rejected'; no broker touch.
  * modify  → leaves status 'pending'; modify-flow lands with the
              memory service in Phase 7.

The executioner refuses to place when mode is 'research', compliance
didn't pass, risk didn't approve/resize, trading is halted, or the
ack is stale.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates

from agents.executioner import Executioner
from models.trade_plan import TradePlan
from models.verdicts import ComplianceVerdict, HumanAckRecord, RiskVerdict
from services import db_service
from services.settings_service import TEMPLATES_DIR, Settings, get_settings
from services.stub_data import time_ago

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


_VALID_STATUSES = ("pending", "approved", "executed", "rejected",
                   "order_rejected", "expired", "all")


def _is_stale(ts_created: str, timeout_minutes: int) -> bool:
    """True if the plan's creation time is older than the ack window.

    Used both to guard the server-side approve path and to drive the
    UI's Approve-button disabled state.
    """
    if not ts_created:
        return False
    try:
        created = datetime.fromisoformat(ts_created.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - created) > timedelta(minutes=timeout_minutes)


def _decorate(p: dict, *, stale_minutes: int) -> dict:
    """Attach UI-friendly derived fields to a pending plan dict.

    ``is_stale`` — true when ``ts_created`` is older than the approval
    window. The template uses this to disable the Approve button.
    """
    if not p:
        return p
    try:
        ts_ago = time_ago(p["ts_created"])
    except Exception:
        ts_ago = ""
    return {
        **p,
        "ts_ago": ts_ago,
        "is_stale": _is_stale(p.get("ts_created") or "", stale_minutes),
    }


async def _filter_rows(status: str) -> list[dict]:
    if status == "all":
        return await db_service.get_pending_plans(status_filter=None)
    return await db_service.get_pending_plans(status_filter=status)


async def _status_counts() -> dict[str, int]:
    """Count rows for every filter state — drives the tab-bar badges."""
    counts = {
        "pending": 0, "approved": 0, "executed": 0, "rejected": 0,
        "order_rejected": 0, "expired": 0, "all": 0,
    }
    all_rows = await db_service.get_pending_plans(status_filter=None, limit=500)
    for r in all_rows:
        s = r.get("status") or "pending"
        counts[s] = counts.get(s, 0) + 1
        counts["all"] += 1
    return counts


def _normalize_status(status: str | None) -> str:
    if not status or status not in _VALID_STATUSES:
        return "pending"
    return status


@router.get("/pending", response_class=HTMLResponse)
async def pending_page(
    request: Request,
    status: str | None = Query(default="pending"),
    s: Settings = Depends(get_settings),
):
    stale_minutes = s.execution.stale_plan_timeout_minutes
    await db_service.expire_stale_plans(timeout_minutes=stale_minutes)
    status = _normalize_status(status)
    rows = await _filter_rows(status)
    counts = await _status_counts()
    return templates.TemplateResponse(
        request=request,
        name="pending.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "pending",
            "pending": [_decorate(p, stale_minutes=stale_minutes) for p in rows],
            "selected": None,
            "filter_status": status,
            "status_counts": counts,
            "stale_minutes": stale_minutes,
        },
    )


@router.get("/pending/{plan_id}", response_class=HTMLResponse)
async def pending_detail(
    plan_id: str, request: Request,
    status: str | None = Query(default="pending"),
    s: Settings = Depends(get_settings),
):
    stale_minutes = s.execution.stale_plan_timeout_minutes
    await db_service.expire_stale_plans(timeout_minutes=stale_minutes)
    status = _normalize_status(status)
    rows = await _filter_rows(status)
    selected = await db_service.get_plan_by_id(plan_id)
    counts = await _status_counts()
    return templates.TemplateResponse(
        request=request,
        name="pending.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "pending",
            "pending": [_decorate(p, stale_minutes=stale_minutes) for p in rows],
            "selected": _decorate(selected, stale_minutes=stale_minutes) if selected else None,
            "not_found": selected is None,
            "filter_status": status,
            "status_counts": counts,
            "stale_minutes": stale_minutes,
        },
    )


@router.post("/pending/{plan_id}/ack", response_class=HTMLResponse)
async def pending_ack(
    plan_id: str,
    action: str = Form(...),
    s: Settings = Depends(get_settings),
):
    """Record the ack. ``approve`` additionally runs the executioner to
    submit the order to the broker.

    ``modify`` is intentionally NOT supported as a distinct flow today —
    the modify UI lands with the memory service in a later phase. If the
    client sends it we refuse with a clear message rather than silently
    leave the plan in pending.
    """
    if action not in {"approve", "reject"}:
        return HTMLResponse(
            f'<span class="toast toast-fail">Unsupported action: {action}. '
            f'Modify is not implemented yet — reject and re-run the '
            f'pipeline if you need different parameters.</span>',
            status_code=400,
        )

    row = await db_service.get_plan_by_id(plan_id)
    if not row:
        return HTMLResponse(
            f'<span class="toast toast-fail">Plan {plan_id} not found.</span>',
            status_code=404,
        )

    # Idempotency: block re-execution of a plan already past pending.
    if action == "approve" and row["status"] != "pending":
        return HTMLResponse(
            f'<span class="toast toast-fail">Plan {plan_id} already '
            f'<strong>{row["status"]}</strong>; cannot approve again.</span>',
            status_code=409,
        )

    # Server-side stale guard: if the plan is older than the approval
    # window, refuse the approval even if the UI let the button slip
    # through (race between countdown and click). Reject is always fine.
    if action == "approve" and _is_stale(
        row["ts_created"], s.execution.stale_plan_timeout_minutes,
    ):
        await db_service.expire_stale_plans(
            timeout_minutes=s.execution.stale_plan_timeout_minutes,
        )
        return HTMLResponse(
            f'<span class="toast toast-fail">Plan {plan_id} has expired '
            f'({s.execution.stale_plan_timeout_minutes}-minute window '
            f'closed). Re-run the pipeline to re-propose.</span>',
            status_code=410,
        )

    # Build the HumanAckRecord — persisted on the row regardless of action.
    ack = HumanAckRecord(
        plan_id=plan_id,
        ts=datetime.now(timezone.utc).isoformat(),
        action=action,  # type: ignore[arg-type]
        ack_by="human",
    )
    await db_service.ack_plan(plan_id, action, ack_record=ack.model_dump())

    # Reject is terminal here — no broker touch.
    if action == "reject":
        return HTMLResponse(
            f'<span class="toast toast-fail">Plan {plan_id} rejected.</span>'
        )

    # Approve → executioner
    try:
        plan = TradePlan.model_validate(row["plan_json"])
    except Exception as e:  # noqa: BLE001
        return HTMLResponse(
            f'<span class="toast toast-fail">Plan JSON invalid: {e}</span>',
            status_code=500,
        )

    compliance = (
        ComplianceVerdict.model_validate(row["compliance_verdict"])
        if row.get("compliance_verdict") else None
    )
    risk = (
        RiskVerdict.model_validate(row["risk_verdict"])
        if row.get("risk_verdict") else None
    )

    exe = Executioner(s)
    result = await exe.execute_plan(
        plan=plan,
        compliance_verdict=compliance,
        risk_verdict=risk,
        ack=ack,
    )
    await db_service.record_execution(plan_id, result.model_dump())

    if result.placed:
        return HTMLResponse(
            f'<span class="toast toast-ok">Order placed — '
            f'broker_order_id=<strong>{result.broker_order_id}</strong> '
            f'({result.broker_name})</span>'
        )
    return HTMLResponse(
        f'<span class="toast toast-fail">Executioner refused: '
        f'{result.reject_reason}</span>',
        status_code=400,
    )


@router.get("/api/pending/count", response_class=PlainTextResponse)
async def pending_count() -> str:
    n = await db_service.get_pending_count()
    return str(n)
