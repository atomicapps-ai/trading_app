"""strategy_live.py — live, graphical view of strategy processing.

Renders a per-symbol grid of cards, each showing the Double Lock
strategy's evaluation state in real time as the trading day
progresses. Cards repaint via HTMX every 30 seconds.

Routes
------
    GET /strategy-live                          → redirect to /strategy-live/dl
    GET /strategy-live/dl                       → page shell
    GET /api/strategy-live/dl/state             → JSON for programmatic clients
    GET /api/strategy-live/dl/cards             → HTML partial (HTMX-polled)

Symbols come from the active universe preset; the bellwether list
(SPY/QQQ/AAPL/...) is the fallback when the preset is empty.
"""
from __future__ import annotations

import asyncio
import logging

import pandas as pd
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from services import dl_live_state
from services.settings_service import TEMPLATES_DIR, get_settings

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


_BELLWETHER = [
    "SPY", "QQQ", "AAPL", "NVDA", "MSFT",
    "TSLA", "AMZN", "META", "GOOGL", "AVGO",
]
_DEFAULT_MAX_SYMBOLS = 12  # cap chart count for readable density


# --------------------------------------------------------------------------- #
# Symbol resolution
# --------------------------------------------------------------------------- #


async def _resolve_symbols(override: str | None) -> list[str]:
    """If `override` (csv) is given, use it. Otherwise active screener
    tickers; otherwise bellwether fallback. Capped at MAX_SYMBOLS."""
    if override:
        syms = [s.strip().upper() for s in override.split(",") if s.strip()]
        return syms[:_DEFAULT_MAX_SYMBOLS]

    try:
        from services import db_service
        active = await db_service.get_active_universe_preset()
        if active and active.get("tickers"):
            return list(active["tickers"])[:_DEFAULT_MAX_SYMBOLS]
    except Exception as exc:                                          # noqa: BLE001
        logger.debug("strategy_live: active preset lookup failed (%s)", exc)
    return _BELLWETHER[:_DEFAULT_MAX_SYMBOLS]


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@router.get("/strategy-live")
async def strategy_live_root():
    return RedirectResponse(url="/strategy-live/dl", status_code=307)


@router.get("/strategy-live/dl", response_class=HTMLResponse)
async def strategy_live_dl(request: Request, symbols: str | None = None):
    s = get_settings()
    syms = await _resolve_symbols(symbols)
    return templates.TemplateResponse(
        request=request,
        name="strategy_live/dl.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "strategy-live",
            "symbols": syms,
            "symbols_param": ",".join(syms),
        },
    )


@router.get("/api/strategy-live/dl/state", response_class=JSONResponse)
async def strategy_live_state(symbols: str | None = None):
    syms = await _resolve_symbols(symbols)
    states = await _evaluate_all(syms)
    return {
        "symbols": [st.to_dict() for st in states],
        "as_of": pd.Timestamp.now(tz="UTC").isoformat(),
    }


@router.get("/api/strategy-live/dl/cards", response_class=HTMLResponse)
async def strategy_live_cards(request: Request, symbols: str | None = None):
    """HTML partial — used by HTMX every 30s. Renders the full grid so the
    chart layer can repaint in place."""
    syms = await _resolve_symbols(symbols)
    states = await _evaluate_all(syms)
    return templates.TemplateResponse(
        request=request,
        name="strategy_live/_cards.html",
        context={
            "states": states,
            "as_of": pd.Timestamp.now(tz="America/New_York").strftime("%H:%M:%S ET"),
        },
    )


async def _evaluate_all(symbols: list[str]) -> list[dl_live_state.LiveState]:
    """Evaluate each symbol concurrently. Failures isolate per symbol."""
    async def _one(sym: str) -> dl_live_state.LiveState:
        try:
            return await dl_live_state.evaluate_symbol(sym)
        except Exception as exc:                                      # noqa: BLE001
            logger.warning("strategy_live: %s evaluate failed: %s", sym, exc)
            return dl_live_state.LiveState(
                symbol=sym,
                as_of_iso=pd.Timestamp.now(tz="UTC").isoformat(),
                failures=[f"evaluation error: {exc}"],
            )
    return await asyncio.gather(*[_one(s) for s in symbols])
