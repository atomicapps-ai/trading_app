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
_DEFAULT_MAX_SYMBOLS = 50   # server-side cap (yfinance rate-limit headroom)
_HARD_MAX_SYMBOLS    = 200  # absolute ceiling; user can request up to this


# --------------------------------------------------------------------------- #
# Symbol resolution
# --------------------------------------------------------------------------- #


async def _resolve_symbols(override: str | None, max_n: int) -> list[str]:
    """If `override` (csv) is given, use it. Otherwise active screener
    tickers; otherwise bellwether fallback. Capped at `max_n`."""
    if override:
        syms = [s.strip().upper() for s in override.split(",") if s.strip()]
        return syms[:max_n]

    try:
        from services import db_service
        active = await db_service.get_active_universe_preset()
        if active and active.get("tickers"):
            return list(active["tickers"])[:max_n]
    except Exception as exc:                                          # noqa: BLE001
        logger.debug("strategy_live: active preset lookup failed (%s)", exc)
    return _BELLWETHER[:max_n]


# Status sort priority — armed first, then strongest evaluation, weakest last.
# Used server-side so the most actionable rows always render at the top.
_STATUS_PRIORITY = {
    "armed":   0,
    "passed":  1,
    "forming": 2,
    "pending": 3,
    "failed":  4,
    "n/a":     5,
}


def _rolled_status(s: "dl_live_state.LiveState") -> str:
    if s.armed:
        return "armed"
    if s.c1_status == "failed" or s.c2_status == "failed" or s.regime_status == "failed":
        return "failed"
    if s.c1_status == "passed" and s.c2_status == "passed" and s.regime_status == "passed":
        return "passed"
    if s.c1_status == "forming" or s.c2_status == "forming":
        return "forming"
    return "pending"


def _sort_states(states: list) -> list:
    """Stable sort by (status priority, -volume_ratio, symbol)."""
    return sorted(
        states,
        key=lambda s: (
            _STATUS_PRIORITY.get(_rolled_status(s), 9),
            -(s.c1_volume_ratio or 0.0),
            s.symbol,
        ),
    )


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #


@router.get("/strategy-live")
async def strategy_live_root():
    return RedirectResponse(url="/strategy-live/dl", status_code=307)


@router.get("/strategy-live/dl", response_class=HTMLResponse)
async def strategy_live_dl(
    request: Request,
    symbols: str | None = None,
    max: int = _DEFAULT_MAX_SYMBOLS,
):
    s = get_settings()
    max_n = min(max, _HARD_MAX_SYMBOLS)
    syms = await _resolve_symbols(symbols, max_n)
    return templates.TemplateResponse(
        request=request,
        name="strategy_live/dl.html",
        context={
            "settings": s,
            "app_version": "0.1.0",
            "active_page": "strategy-live",
            "symbols": syms,
            "symbols_param": ",".join(syms),
            "max_n": max_n,
            # When N is large, default to compact table — grid of 50+
            # charts is unreadable. User can flip via toolbar.
            "default_density": "table" if len(syms) > 20 else "grid",
        },
    )


@router.get("/api/strategy-live/dl/state", response_class=JSONResponse)
async def strategy_live_state(
    symbols: str | None = None, max: int = _DEFAULT_MAX_SYMBOLS,
):
    max_n = min(max, _HARD_MAX_SYMBOLS)
    syms = await _resolve_symbols(symbols, max_n)
    states = _sort_states(await _evaluate_all(syms))
    return {
        "symbols": [st.to_dict() for st in states],
        "as_of": pd.Timestamp.now(tz="UTC").isoformat(),
    }


@router.get("/api/strategy-live/dl/cards", response_class=HTMLResponse)
async def strategy_live_cards(
    request: Request, symbols: str | None = None,
    max: int = _DEFAULT_MAX_SYMBOLS,
):
    """HTML partial — used by HTMX every 30s. Renders the full grid so the
    chart layer can repaint in place."""
    max_n = min(max, _HARD_MAX_SYMBOLS)
    syms = await _resolve_symbols(symbols, max_n)
    states = _sort_states(await _evaluate_all(syms))
    counts = _status_counts(states)
    return templates.TemplateResponse(
        request=request,
        name="strategy_live/_cards.html",
        context={
            "states": states,
            "rolled": {s.symbol: _rolled_status(s) for s in states},
            "counts": counts,
            "as_of": pd.Timestamp.now(tz="America/New_York").strftime("%H:%M:%S ET"),
        },
    )


def _status_counts(states: list) -> dict[str, int]:
    out = {"all": len(states), "armed": 0, "passed": 0,
           "forming": 0, "pending": 0, "failed": 0}
    for s in states:
        out[_rolled_status(s)] = out.get(_rolled_status(s), 0) + 1
    return out


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
