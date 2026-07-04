"""TradeAgent FastAPI entrypoint.

Phase 3: routers wired (dashboard, pending, trades, settings, broker, stubs);
broker adapter selected at startup based on `settings.app.mode`. App must
remain usable even if broker connect fails (e.g. .env not configured).

Run locally:
    uvicorn app:app --reload --host 0.0.0.0 --port 5000
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from routers import (
    alerts,
    analysis,
    auth as auth_router,
    bars,
    broker,
    copy_trading,
    dashboard,
    data_fetch,
    favorites,
    indicators,
    jobs,
    live_status as live_status_router,
    manual_trade as manual_trade_router,
    news_detail,
    pending,
    positions as positions_router,
    pwa as pwa_router,
    replay as replay_router,
    research as research_router,
    settings as settings_router,
    stock_lists,
    strategies as strategies_router,
    strategy_live as strategy_live_router,
    stubs,
    system_health as system_health_router,
    today as today_router,
    trade_detail,
    trades,
    universe,
    workflows,
)
from services import db_service, universe_service
from services.broker_service import connect_adapter, get_adapter
from services.settings_service import (
    ENV_FILE,
    PROJECT_ROOT,
    STATIC_DIR,
    Settings,
    ensure_directories,
    get_settings,
)

# Load .env BEFORE any os.getenv() calls in adapter modules.
load_dotenv(ENV_FILE, override=False)

# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
)
logger = logging.getLogger("trading_app")


# --------------------------------------------------------------------------- #
# Lifespan — bootstrap directories + connect broker (gracefully)
# --------------------------------------------------------------------------- #
@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_directories()
    s = get_settings()
    logger.info(
        "TradeAgent starting | mode=%s | project_root=%s", s.app.mode, PROJECT_ROOT
    )
    try:
        await db_service.ensure_tables()
        await universe_service.seed_from_yaml_if_empty()
        # Restore any screeners present in the committed YAML backup but
        # missing from the DB (handles fresh checkout, DB rebuild, etc).
        # Additive only — never overwrites an existing row.
        await universe_service.import_screeners_from_yaml()
    except Exception as exc:
        logger.error("SQLite ensure_tables failed: %s", exc)
    try:
        # First boot only: populate broker_accounts from .env credentials.
        # No-op on subsequent boots — registry is owned by the user via UI.
        from services import account_service
        await account_service.ensure_seeded_from_env()
    except Exception as exc:
        logger.error("Broker accounts seed failed: %s", exc)
    try:
        ok = await connect_adapter()
        logger.info("Broker adapter: %s", "connected" if ok else "failed")
    except Exception as exc:
        logger.error("Broker adapter failed to connect: %s", exc)
    try:
        from services.scheduler import start_scheduler
        start_scheduler()
    except Exception as exc:
        logger.error("Scheduler failed to start: %s", exc)
    # Prewarm the SEC ticker→CIK map in the background so the first
    # /trades/{id} render after a fresh checkout doesn't stall on the
    # ~3s SEC download. Fire-and-forget — failures are logged inside
    # prewarm_cik_map and never bubble up.
    try:
        import asyncio as _asyncio
        from services.news_service import prewarm_cik_map
        _asyncio.create_task(prewarm_cik_map())
    except Exception as exc:
        logger.error("CIK prewarm task scheduling failed: %s", exc)
    yield
    try:
        from services.scheduler import stop_scheduler
        stop_scheduler()
    except Exception as exc:
        logger.warning("Scheduler stop raised: %s", exc)
    try:
        adapter = get_adapter()
        if adapter.connected:
            await adapter.disconnect()
    except Exception as exc:
        logger.warning("Broker disconnect raised: %s", exc)
    logger.info("TradeAgent shutting down")


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #
app = FastAPI(
    title="TradeAgent",
    description="Multi-agent trading workflow manager",
    version="0.1.0",
    lifespan=lifespan,
)

ensure_directories()

# Auth gate — pass-through unless APP_AUTH_PASSWORD is set (local dev unchanged).
# Added before routers so it wraps every request. Warn loudly if it's off, since
# an internet-exposed deployment without it would be wide open.
from services.auth_middleware import AuthMiddleware  # noqa: E402
from services.auth_service import auth_enabled  # noqa: E402

app.add_middleware(AuthMiddleware)
if auth_enabled():
    logger.info("Auth: ENABLED (session password gate active)")
else:
    logger.warning(
        "Auth: DISABLED — no APP_AUTH_PASSWORD set. Fine for local use; set it "
        "before exposing the app to the internet (Cloudflare Tunnel, etc.)."
    )

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(auth_router.router)
app.include_router(pwa_router.router)
app.include_router(dashboard.router)
app.include_router(alerts.router)
app.include_router(pending.router)
app.include_router(manual_trade_router.router)
app.include_router(trades.router)
app.include_router(analysis.router)
app.include_router(trade_detail.router)
app.include_router(news_detail.router)
app.include_router(settings_router.router)
app.include_router(broker.router)
app.include_router(positions_router.router)
app.include_router(live_status_router.router)
app.include_router(workflows.router)
app.include_router(jobs.router)
app.include_router(strategies_router.router)
app.include_router(strategy_live_router.router)
app.include_router(replay_router.router)
app.include_router(today_router.router)
app.include_router(system_health_router.router)
app.include_router(bars.router)
app.include_router(data_fetch.router)
app.include_router(research_router.router)
app.include_router(indicators.router)
# Register stock_lists BEFORE universe — universe has /universe/{preset_name}
# which would shadow /universe/stock-lists if mounted in the wrong order.
app.include_router(stock_lists.router)
app.include_router(universe.router)
app.include_router(copy_trading.router)
app.include_router(favorites.router)
app.include_router(stubs.router)


# --------------------------------------------------------------------------- #
# Health endpoint (kept on the app, not in a router)
# --------------------------------------------------------------------------- #
@app.get("/health")
async def health(s: Settings = Depends(get_settings)) -> dict:
    return {
        "status": "ok",
        "mode": s.app.mode,
        "ts": datetime.now(timezone.utc).isoformat(),
        "version": app.version,
    }
