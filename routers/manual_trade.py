"""manual_trade router — create / copy / execute an operator-entered trade.

    GET  /trades/new                 → manual trade form (?copy_from=<plan_id> prefills)
    POST /api/trades/manual          → build + gate + queue to /pending
    POST /api/trades/manual/execute  → build + gate + place a market order NOW
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from services import db_service, manual_trade_service
from services.settings_service import TEMPLATES_DIR, Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _prefill_from_plan(plan_row: dict | None) -> dict:
    if not plan_row:
        return {}
    plan = plan_row.get("plan") or plan_row  # tolerate either shape
    setup = plan.get("setup") or {}
    entry = setup.get("entry") or {}
    stop = (setup.get("stop_loss") or {}).get("initial") or {}
    tps = setup.get("take_profit") or []
    instr = plan.get("instrument") or {}
    return {
        "symbol": instr.get("symbol") or plan_row.get("symbol", ""),
        "direction": setup.get("direction", "long"),
        "entry_type": entry.get("type", "limit"),
        "entry_price": entry.get("price", ""),
        "stop_price": stop.get("price", ""),
        "tp1_price": tps[0]["price"] if len(tps) >= 1 else "",
        "tp2_price": tps[1]["price"] if len(tps) >= 2 else "",
        "shares": (plan.get("risk") or {}).get("position_size_shares", ""),
    }


@router.get("/trades/new", response_class=HTMLResponse)
async def new_trade_page(
    request: Request, copy_from: str | None = None,
    s: Settings = Depends(get_settings),
):
    prefill: dict = {}
    if copy_from:
        try:
            row = await db_service.get_plan_by_id(copy_from)
            prefill = _prefill_from_plan(row)
        except Exception as e:                                    # noqa: BLE001
            logger.warning("copy_from %s failed: %s", copy_from, e)
    return templates.TemplateResponse(
        request=request, name="manual_trade.html",
        context={"settings": s, "app_version": "0.1.0",
                 "active_page": "pending", "prefill": prefill,
                 "is_copy": bool(copy_from)},
    )


async def _build_and_run(form: dict, settings: Settings, execute_now: bool) -> JSONResponse:
    def _f(key):
        v = form.get(key)
        if v is None or str(v).strip() == "":
            return None
        try:
            return float(v)
        except ValueError:
            return None
    try:
        plan = await manual_trade_service.build_plan(
            symbol=str(form.get("symbol", "")),
            direction=str(form.get("direction", "long")),       # type: ignore[arg-type]
            entry_type=str(form.get("entry_type", "limit")),    # type: ignore[arg-type]
            entry_price=_f("entry_price") or 0.0,
            stop_price=_f("stop_price") or 0.0,
            tp1_price=_f("tp1_price"),
            tp2_price=_f("tp2_price"),
            dollars=_f("dollars"),
            shares=int(_f("shares")) if _f("shares") else None,
            settings=settings,
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:                                       # noqa: BLE001
        logger.exception("manual build_plan failed")
        return JSONResponse({"error": f"build failed: {e}"}, status_code=500)

    try:
        result = await manual_trade_service.gate_and_queue(
            plan, settings, execute_now=execute_now)
    except Exception as e:                                       # noqa: BLE001
        logger.exception("manual gate_and_queue failed")
        return JSONResponse({"error": f"gate/execute failed: {e}"}, status_code=500)
    return JSONResponse(result)


@router.post("/api/trades/manual", response_class=JSONResponse)
async def create_manual(request: Request, s: Settings = Depends(get_settings)):
    form = dict(await request.form())
    return await _build_and_run(form, s, execute_now=False)


@router.post("/api/trades/manual/execute", response_class=JSONResponse)
async def execute_manual(request: Request, s: Settings = Depends(get_settings)):
    form = dict(await request.form())
    return await _build_and_run(form, s, execute_now=True)
