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
    bars,
    broker,
    dashboard,
    indicators,
    pending,
    settings as settings_router,
    stubs,
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
    except Exception as exc:
        logger.error("SQLite ensure_tables failed: %s", exc)
    try:
        ok = await connect_adapter()
        logger.info("Broker adapter: %s", "connected" if ok else "failed")
    except Exception as exc:
        logger.error("Broker adapter failed to connect: %s", exc)
    yield
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
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(dashboard.router)
app.include_router(pending.router)
app.include_router(trades.router)
app.include_router(settings_router.router)
app.include_router(broker.router)
app.include_router(workflows.router)
app.include_router(bars.router)
app.include_router(indicators.router)
app.include_router(universe.router)
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
