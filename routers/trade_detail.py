"""trade_detail router — unified detail page for any trade by id.

Resolves an id across both backends (pending_approvals + JSONL trade
journal) via ``services.trade_lookup`` and renders the same template
in either case. Active trades get the edit form; closed trades get
the postmortem card.

Companion partials in templates/_partials/:
  _probability_card.html — backtest WR + live WR + blended
  _news_card.html        — VADER-scored Alpaca News + EDGAR
  _postmortem_card.html  — closed trades only

The chart on the page renders via the shared ``static/chart_tools.js``
helper (same code path as /pending and /universe edit), with a
``persistKey: "trade_detail"`` so per-user indicator picks survive in
localStorage.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from services import (
    db_service,
    news_service,
    probability_service,
    sentiment_service,
    trade_lookup,
)
from services.settings_service import TEMPLATES_DIR, Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@router.get("/trades/{trade_id}", response_class=HTMLResponse)
async def trade_detail(
    trade_id: str, request: Request,
    s: Settings = Depends(get_settings),
):
    """Single-trade detail page. Works for pending OR closed trades."""
    trade = await trade_lookup.get(trade_id)
    if trade is None:
        raise HTTPException(404, f"trade {trade_id} not found")

    # ── Probability of success (strategy-level) ─────────────────────────
    prob = None
    if trade.strategy_name:
        try:
            prob = (await probability_service.compute(trade.strategy_name)).to_dict()
        except Exception as e:                                # noqa: BLE001
            logger.warning("trade_detail: probability failed for %s: %s",
                           trade.strategy_name, e)

    # ── News + sentiment (last 24h, scored) ─────────────────────────────
    news_items: list[dict] = []
    news_summary: dict = {}
    news_error: str | None = None
    try:
        end   = datetime.now(timezone.utc)
        start = end - timedelta(hours=24)
        items = await news_service.get_news(trade.symbol, start=start, end=end)
        if items:
            scored = sentiment_service.score_items(items)
            news_items = [s.to_dict() for s in scored]
            news_summary = sentiment_service.summarize(items).to_dict()
    except Exception as e:                                    # noqa: BLE001
        news_error = f"News fetch failed: {e}"
        logger.warning("trade_detail: news fetch failed for %s: %s",
                       trade.symbol, e)

    return templates.TemplateResponse(
        request=request,
        name="trades/detail.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "trades",
            "trade": trade,
            "probability": prob,
            "news_items": news_items,
            "news_summary": news_summary,
            "news_error": news_error,
        },
    )


# --------------------------------------------------------------------------- #
# Indicator-pick persistence — POST {ids} for the trade chart picker
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Edit-mode for active trades — Phase 6
# --------------------------------------------------------------------------- #

# Stages where each editable field still makes sense to mutate.
#   pending  — TradePlan only; no broker order yet. Anything goes.
#   approved — entry order is live at the broker; entry edit goes via
#              modify_order. Stop/TP/deadline are still TradePlan-only.
#   open     — entry already filled; entry edit is meaningless. Stop/TP/
#              deadline still update the plan and (for deadline) the
#              scheduled close.
_EDITABLE_STAGES = {"pending", "approved", "open"}
_BROKER_EDITABLE_STAGES = {"pending", "approved"}


def _parse_optional_float(s: str | None) -> float | None:
    if s is None:
        return None
    s = s.strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        raise HTTPException(400, f"not a number: {s!r}")


def _parse_optional_deadline(s: str | None) -> str | None:
    """HTML datetime-local sends a naive 'YYYY-MM-DDTHH:MM' string. We
    interpret it as ET (the trading session timezone) and emit UTC ISO."""
    if s is None or s.strip() == "":
        return None
    from zoneinfo import ZoneInfo
    try:
        naive = datetime.strptime(s.strip(), "%Y-%m-%dT%H:%M")
    except ValueError:
        raise HTTPException(400, f"bad deadline format: {s!r}")
    et = naive.replace(tzinfo=ZoneInfo("America/New_York"))
    return et.astimezone(timezone.utc).isoformat()


def _changes_for_broker(
    old_plan: dict, new_plan: dict,
) -> dict:
    """Return the subset of changes that should be sent to the broker.

    Phase 4 placed the entry order only — stop/TP brackets aren't on
    the broker, so the only actionable broker change here is the entry
    limit price. Quantity is fixed by risk_manager and not editable
    from this form.
    """
    old_entry = (old_plan.get("setup", {}).get("entry") or {}).get("price")
    new_entry = (new_plan.get("setup", {}).get("entry") or {}).get("price")
    if old_entry == new_entry:
        return {}
    if new_entry is None:
        return {}
    return {"limit_price": float(new_entry)}


@router.post("/api/trades/{trade_id}/edit", response_class=HTMLResponse)
async def trade_edit(
    trade_id: str,
    entry_price: str | None = Form(default=None),
    stop_price: str | None = Form(default=None),
    tp1_price: str | None = Form(default=None),
    tp2_price: str | None = Form(default=None),
    time_stop_deadline: str | None = Form(default=None),
    s: Settings = Depends(get_settings),
):
    """Apply level edits to an active trade.

    Updates the stored TradePlan in SQLite, optionally pushes the entry
    edit to the broker, and reschedules the timed close if the deadline
    moved. Returns an HTMX-friendly toast.
    """
    plan_row = await db_service.get_plan_by_id(trade_id)
    if plan_row is None:
        return HTMLResponse(
            f'<span class="toast toast-fail">Trade {trade_id} not found.</span>',
            status_code=404,
        )

    view = await trade_lookup.get(trade_id)
    if view is None or view.stage not in _EDITABLE_STAGES:
        return HTMLResponse(
            f'<span class="toast toast-fail">Trade is in stage '
            f'<strong>{(view.stage if view else "unknown")}</strong> — not editable.</span>',
            status_code=409,
        )

    plan = plan_row.get("plan_json") or {}
    if not isinstance(plan, dict) or not plan.get("setup"):
        return HTMLResponse(
            '<span class="toast toast-fail">Plan JSON malformed.</span>',
            status_code=500,
        )

    # Parse + validate inputs (raises HTTPException on garbage)
    try:
        new_entry = _parse_optional_float(entry_price)
        new_stop  = _parse_optional_float(stop_price)
        new_tp1   = _parse_optional_float(tp1_price)
        new_tp2   = _parse_optional_float(tp2_price)
        new_dl    = _parse_optional_deadline(time_stop_deadline)
    except HTTPException as e:
        return HTMLResponse(
            f'<span class="toast toast-fail">{e.detail}</span>',
            status_code=e.status_code,
        )

    # Snapshot the old plan so we can diff for broker changes
    import copy
    new_plan = copy.deepcopy(plan)
    setup = new_plan.setdefault("setup", {})
    if new_entry is not None:
        setup.setdefault("entry", {})["price"] = round(new_entry, 2)
    if new_stop is not None:
        setup.setdefault("stop_loss", {}).setdefault(
            "initial", {})["price"] = round(new_stop, 2)
    tps = setup.setdefault("take_profit", [])
    if new_tp1 is not None:
        if len(tps) >= 1:
            tps[0]["price"] = round(new_tp1, 2)
        else:
            tps.append({"leg": 1, "price": round(new_tp1, 2),
                        "size_pct": 50, "reason": "manual_edit"})
    if new_tp2 is not None:
        if len(tps) >= 2:
            tps[1]["price"] = round(new_tp2, 2)
        elif len(tps) == 1:
            tps.append({"leg": 2, "price": round(new_tp2, 2),
                        "size_pct": 50, "reason": "manual_edit"})
    if new_dl is not None:
        ts = setup.setdefault("stop_loss", {}).setdefault(
            "time_stop",
            {"active": True, "condition": "manual edit", "deadline": new_dl},
        )
        ts["deadline"] = new_dl
        ts["active"] = True

    # Persist the plan first so the rest of the app sees the new levels
    # even if a downstream step (broker call, reschedule) fails.
    ok = await db_service.update_plan_json(trade_id, new_plan)
    if not ok:
        return HTMLResponse(
            '<span class="toast toast-fail">DB update failed.</span>',
            status_code=500,
        )

    # Best-effort broker push for the entry edit (only meaningful while
    # the entry order is still working at the broker).
    broker_msg = ""
    broker_order_id = plan_row.get("broker_order_id")
    if (
        broker_order_id
        and view.stage in _BROKER_EDITABLE_STAGES
        and (broker_changes := _changes_for_broker(plan, new_plan))
    ):
        from services import broker_service
        try:
            adapter = broker_service.get_adapter()
            if not adapter.connected:
                await adapter.connect()
            ack = await adapter.modify_order(broker_order_id, broker_changes)
            if ack.accepted:
                broker_msg = f" · broker entry updated"
            else:
                broker_msg = f" · broker rejected: {ack.reject_reason}"
        except Exception as e:                                # noqa: BLE001
            logger.warning("modify_order failed for %s: %s", trade_id, e)
            broker_msg = f" · broker error: {e}"

    # Reschedule the timed close if the deadline moved. The scheduling
    # call is idempotent — same job-id replaces.
    if new_dl is not None:
        try:
            from agents.executioner import Executioner
            from models.trade_plan import TradePlan
            qty = (plan_row.get("plan_json", {}).get("risk", {}) or {}).get(
                "position_size_shares") or view.position_size or 0
            tp = TradePlan.model_validate(new_plan)
            Executioner(s).close_at_time(tp, new_dl, int(qty))
        except Exception as e:                                # noqa: BLE001
            logger.warning("close_at_time reschedule failed for %s: %s",
                           trade_id, e)
            broker_msg += f" · close-reschedule failed: {e}"

    return HTMLResponse(
        f'<span class="toast toast-ok">Plan updated{broker_msg}.</span>'
    )
