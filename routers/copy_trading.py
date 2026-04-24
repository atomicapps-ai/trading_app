"""copy_trading.py — Capitol Trades politician copy-trading routes.

Routes
------
GET  /copy-trading                    → dashboard page
GET  /api/copy-trading/config         → JSON: current config
POST /api/copy-trading/config         → update config (followed politician, limits, toggle)
GET  /api/copy-trading/politicians    → JSON: ranked politicians from recent CT trades
GET  /api/copy-trading/trades         → JSON: CT trades for monitored politician (from DB)
POST /api/copy-trading/scan           → manual trigger: fetch CT now, return summary
GET  /api/copy-trading/queue          → JSON: copy trade queue (recent DB records)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from services import db_service
from services.capitol_trades_service import CapitolTradesService
from services.settings_service import TEMPLATES_DIR, Settings, get_settings

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)

_svc = CapitolTradesService()

# --------------------------------------------------------------------------- #
# HTML page
# --------------------------------------------------------------------------- #


@router.get("/copy-trading", response_class=HTMLResponse)
async def copy_trading_page(
    request: Request,
    s: Settings = Depends(get_settings),
) -> HTMLResponse:
    cfg = await db_service.get_all_copy_config()
    recent_trades = await db_service.list_politician_trades(
        politician_slug=cfg.get("followed_politician"), limit=50
    )
    return templates.TemplateResponse(
        request=request,
        name="copy_trading.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "copy_trading",
            "config": cfg,
            "recent_trades": recent_trades,
        },
    )


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


class CopyConfigUpdate(BaseModel):
    followed_politician: str | None = None
    followed_politician_name: str | None = None
    max_per_trade_usd: float | None = None
    enabled: bool | None = None


@router.get("/api/copy-trading/config")
async def get_config() -> dict:
    cfg = await db_service.get_all_copy_config()
    return _enrich_config(cfg)


@router.post("/api/copy-trading/config")
async def update_config(body: CopyConfigUpdate) -> dict:
    if body.followed_politician is not None:
        await db_service.set_copy_config("followed_politician", body.followed_politician)
    if body.followed_politician_name is not None:
        await db_service.set_copy_config("followed_politician_name", body.followed_politician_name)
    if body.max_per_trade_usd is not None:
        await db_service.set_copy_config("max_per_trade_usd", str(body.max_per_trade_usd))
    if body.enabled is not None:
        await db_service.set_copy_config("enabled", "true" if body.enabled else "false")
    return {"ok": True, "config": _enrich_config(await db_service.get_all_copy_config())}


def _enrich_config(cfg: dict) -> dict:
    return {
        "followed_politician": cfg.get("followed_politician", ""),
        "followed_politician_name": cfg.get("followed_politician_name", ""),
        "max_per_trade_usd": float(cfg.get("max_per_trade_usd", "5000")),
        "enabled": cfg.get("enabled", "true") == "true",
        "last_scan_ts": cfg.get("last_scan_ts", ""),
        "last_scan_count": int(cfg.get("last_scan_count", "0")),
        "last_scan_error": cfg.get("last_scan_error", ""),
    }


# --------------------------------------------------------------------------- #
# Politicians ranking
# --------------------------------------------------------------------------- #


@router.get("/api/copy-trading/politicians")
async def get_politicians(pages: int = 5) -> dict:
    """Fetch recent Capitol Trades data and return ranked politician list."""
    try:
        trades = await _svc.fetch_recent_trades(pages=pages)
        ranked = _svc.rank_politicians(trades, top_n=25)
        return {
            "ok": True,
            "total_trades_fetched": len(trades),
            "politicians": [
                {
                    "name": p.politician_name,
                    "slug": p.politician_slug,
                    "party": p.party,
                    "chamber": p.chamber,
                    "trade_count_90d": p.trade_count_90d,
                    "last_trade_date": p.last_trade_date,
                    "days_since_last_trade": p.days_since_last_trade,
                    "unique_tickers": p.unique_tickers,
                    "buy_ratio_pct": round(p.buy_ratio * 100, 0),
                    "score": p.score,
                }
                for p in ranked
            ],
        }
    except Exception as exc:
        logger.exception("get_politicians failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Capitol Trades fetch failed: {exc}")


# --------------------------------------------------------------------------- #
# Recent trades feed
# --------------------------------------------------------------------------- #


@router.get("/api/copy-trading/trades")
async def get_politician_trades(politician_slug: str | None = None, limit: int = 50) -> dict:
    """Return trades for the monitored politician from our DB."""
    cfg = await db_service.get_all_copy_config()
    slug = politician_slug or cfg.get("followed_politician", "")
    rows = await db_service.list_politician_trades(politician_slug=slug or None, limit=limit)
    return {"ok": True, "trades": rows}


# --------------------------------------------------------------------------- #
# Manual scan trigger
# --------------------------------------------------------------------------- #


@router.post("/api/copy-trading/scan")
async def manual_scan(s: Settings = Depends(get_settings)) -> dict:
    """Fetch Capitol Trades right now and process any new trades."""
    from services.scheduler import _poll_capitol_trades_job

    try:
        await _poll_capitol_trades_job()
        cfg = await db_service.get_all_copy_config()
        return {
            "ok": True,
            "last_scan_ts": cfg.get("last_scan_ts", ""),
            "last_scan_count": int(cfg.get("last_scan_count", "0")),
            "error": cfg.get("last_scan_error", ""),
        }
    except Exception as exc:
        logger.exception("manual_scan failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# --------------------------------------------------------------------------- #
# Copy queue
# --------------------------------------------------------------------------- #


@router.get("/api/copy-trading/queue")
async def get_copy_queue(limit: int = 100) -> dict:
    """All politician trades we've seen with their copy status."""
    rows = await db_service.list_politician_trades(limit=limit)
    return {"ok": True, "trades": rows}
