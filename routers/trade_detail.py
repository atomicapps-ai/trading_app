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
from datetime import datetime, timezone

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

    # ── News + sentiment (multi-source aggregator) ──────────────────────
    # Routes through the news_sources registry so all enabled providers
    # — Alpaca, EDGAR, Webull, plus any new ones — contribute to a single
    # ranked stream. The user's saved source toggles on the dashboard's
    # Market Headlines widget propagate here so a trade detail page
    # respects the same on/off state.
    news_items: list[dict] = []
    news_summary: dict = {}
    news_error: str | None = None
    NEWS_LOOKBACK_HOURS = 72
    MAX_NEWS_RENDERED = 30

    from services.news_sources import default_enabled_source_ids
    from services import widget_settings as ws
    saved_sources = await ws.get_with_default(
        "default", "market_headlines", "enabled_sources",
        default_enabled_source_ids(),
    )

    try:
        items = await news_service.get_news_multi_source(
            trade.symbol,
            source_ids=list(saved_sources) if saved_sources else None,
            lookback_hours=NEWS_LOOKBACK_HOURS,
        )
    except Exception as e:                                    # noqa: BLE001
        items = []
        news_error = f"News fetch failed: {e}"
        logger.warning("trade_detail: news fetch failed for %s: %s",
                       trade.symbol, e)

    if items:
        # Cap so a busy ticker doesn't dominate the page. Aggregate
        # stats run over the visible cap so the "n articles" badge
        # matches what the user sees.
        items = items[:MAX_NEWS_RENDERED]
        scored = sentiment_service.score_items(items)
        for src_item, sc in zip(items, scored):
            d = sc.to_dict()
            d["article_id"] = src_item.article_id
            d["summary"] = src_item.summary
            d["image_url"] = src_item.image_url
            d["tags"] = src_item.tags or []
            d["detail_url"] = (
                f"/news/{src_item.source}/{src_item.article_id}"
            )
            # Pull structured form_type out of the EDGAR headline so the
            # partial can render a colored badge (8-K / 10-Q / 10-K / S-1 etc.)
            # instead of the raw "FORM: title" prefix in the body text.
            if src_item.source == "edgar" and ": " in src_item.headline:
                form_type, _, rest = src_item.headline.partition(": ")
                d["form_type"] = form_type.strip()
                d["display_headline"] = rest.strip() or src_item.headline
            else:
                d["form_type"] = (
                    src_item.extra.get("form_type")
                    if src_item.extra else None
                )
                d["display_headline"] = src_item.headline
            news_items.append(d)
        news_summary = sentiment_service.summarize(items).to_dict()

    from services.tradingview import tv_for_trade
    tradingview_url = tv_for_trade(trade.symbol, trade.strategy_name)

    # Company name for the header label + faint chart watermark (cached;
    # off-thread so a first-time yfinance lookup can't block the event loop).
    company_name = ""
    try:
        import asyncio
        from services import company_service
        company_name = (await asyncio.to_thread(company_service.get_name, trade.symbol)) or ""
    except Exception:                                             # noqa: BLE001
        company_name = ""

    # ── Trade intelligence: payoff geometry + live technical read ────────
    # Populated for ANY trade (incl. manual, no-strategy) so the card is never
    # blank. Strategy win-rate (`prob`) is layered on top when available.
    intel: dict = {"payoff": None, "technical": None}
    try:
        e, sp = trade.entry_price, trade.stop_price
        if e and sp and e != sp:
            direction = (trade.direction or "long").lower()
            risk = abs(e - sp)

            def _rr(tp):
                if not tp:
                    return None
                reward = (tp - e) if direction == "long" else (e - tp)
                return round(reward / risk, 2) if risk else None

            def _be(r):
                return round(100.0 / (1.0 + r), 1) if (r and r > 0) else None

            rr1, rr2 = _rr(trade.tp1_price), _rr(trade.tp2_price)
            intel["payoff"] = {
                "risk_per_share": round(risk, 2),
                "rr1": rr1, "rr2": rr2,
                "breakeven_wr1": _be(rr1), "breakeven_wr2": _be(rr2),
            }
    except Exception:                                             # noqa: BLE001
        pass
    try:
        import pandas as pd
        from services import data_service, indicator_service
        df = await data_service.get_bars(trade.symbol, "1d")
        if df is not None and len(df) >= 30:
            df = indicator_service.add_indicators(df)
            row = df.iloc[-1]

            def _g(k):
                v = row.get(k)
                return float(v) if (v is not None and pd.notna(v)) else None

            close, sma50, sma200 = _g("close"), _g("sma_50"), _g("sma_200")
            rsi, atrp, adx = _g("rsi_14"), _g("atr_14_pct"), _g("adx_14")
            trend = "n/a"
            if close and sma50 and sma200:
                if close > sma50 > sma200:   trend = "uptrend"
                elif close < sma50 < sma200: trend = "downtrend"
                else:                        trend = "mixed"
            rsi_label = None
            if rsi is not None:
                rsi_label = "overbought" if rsi >= 70 else ("oversold" if rsi <= 30 else "neutral")
            intel["technical"] = {
                "close": round(close, 2) if close else None,
                "trend": trend,
                "above_sma50": (close > sma50) if (close and sma50) else None,
                "above_sma200": (close > sma200) if (close and sma200) else None,
                "rsi": round(rsi, 1) if rsi is not None else None,
                "rsi_label": rsi_label,
                "atr_pct": round(atrp, 2) if atrp is not None else None,
                "adx": round(adx, 1) if adx is not None else None,
            }
    except Exception as _e:                                       # noqa: BLE001
        logger.warning("trade_detail: technical read failed for %s: %s", trade.symbol, _e)

    return templates.TemplateResponse(
        request=request,
        name="trades/detail.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "trades",
            "trade": trade,
            "company_name": company_name,
            "intel": intel,
            "probability": prob,
            "tradingview_url": tradingview_url,
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

    # Record alert + ntfy push so the operator (and audit trail) sees
    # exactly what changed. Best-effort — never fails the edit.
    try:
        from services import alert_service
        instr = (plan_row.get("plan_json") or {}).get("instrument") or {}
        sym = instr.get("symbol") or "?"
        # Build a one-line "what changed" string
        diffs = []
        if new_entry is not None: diffs.append(f"entry=${new_entry:.2f}")
        if new_stop  is not None: diffs.append(f"stop=${new_stop:.2f}")
        if new_tp1   is not None: diffs.append(f"tp1=${new_tp1:.2f}")
        if new_tp2   is not None: diffs.append(f"tp2=${new_tp2:.2f}")
        if new_dl    is not None: diffs.append(f"close@{new_dl[11:16]}")
        diff_line = " · ".join(diffs) if diffs else "no changes"
        await alert_service.record_alert(
            kind="manual_edit",
            strategy=plan_row.get("strategy") or "manual",
            symbol=sym,
            direction=(plan_row.get("plan_json") or {}).get("setup", {}).get("direction"),
            plan_id=trade_id,
            title=f"{sym} plan edited — {diff_line}",
            body=f"Manual edit on /trades/{trade_id}{broker_msg}",
            payload={"changes": diffs, "broker_msg": broker_msg.strip(" · ")},
        )
    except Exception as exc:                                          # noqa: BLE001
        logger.warning("alert recording for manual_edit failed: %s", exc)

    return HTMLResponse(
        f'<span class="toast toast-ok">Plan updated{broker_msg}.</span>'
    )
