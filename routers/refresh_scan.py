"""routers/refresh_scan.py — the one-click "Refresh & Scan" button.

A single manual action from the top nav strip:
  POST /api/refresh-and-scan          → start a background run (idempotent)
  GET  /api/refresh-and-scan/status   → poll progress + result

The heavy work (candle top-up + four gate-pipeline scans) runs in a
background task inside ``refresh_scan_service``; these endpoints only
start it and report state.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from services import refresh_scan_service as svc
from services.settings_service import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/refresh-and-scan")
async def start_refresh_and_scan() -> JSONResponse:
    already = svc.is_running()
    run = await svc.start_run(settings=get_settings())
    return JSONResponse({"started": not already, "already_running": already,
                         "run": run})


@router.get("/api/refresh-and-scan/status")
async def refresh_and_scan_status() -> JSONResponse:
    run = svc.get_status()
    return JSONResponse({"run": run, "running": svc.is_running()})
