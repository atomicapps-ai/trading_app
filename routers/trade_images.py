"""trade_images.py — store per-trade chart images generated in the browser.

Option B of the backtest-images design: the browser renders the trade on the
app's own Lightweight Charts (entry/stop/TP markers), screenshots it, and POSTs
the PNG here. We store it under ``data/trade_images/<key>.png`` (served by the
``/trade-images`` mount) so the history table can show a thumbnail. No
server-side plotting dependency.

Routes:
    POST /api/trade-images/{key}   → save a base64 PNG (JSON: {"image": "data:image/png;base64,..."})
    GET  /api/trade-images/{key}   → {exists, url}
    (the PNG itself is served by the /trade-images static mount)
"""
from __future__ import annotations

import base64
import logging
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from services.settings_service import DATA_DIR

logger = logging.getLogger(__name__)
router = APIRouter()

TRADE_IMG_DIR = DATA_DIR / "trade_images"
_SAFE_KEY = re.compile(r"^[A-Za-z0-9._-]{1,120}$")
_MAX_BYTES = 4 * 1024 * 1024   # 4 MB — a chart PNG is well under this


def _path_for(key: str):
    if not _SAFE_KEY.match(key):
        raise HTTPException(400, "invalid image key")
    return TRADE_IMG_DIR / f"{key}.png"


@router.post("/api/trade-images/{key}")
async def save_trade_image(key: str, request: Request) -> JSONResponse:
    path = _path_for(key)
    body = await request.json()
    data_url = (body or {}).get("image") or ""
    # Accept a data URL or a bare base64 string.
    if "," in data_url and data_url.strip().lower().startswith("data:"):
        data_url = data_url.split(",", 1)[1]
    try:
        raw = base64.b64decode(data_url, validate=True)
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "image must be base64 PNG data")
    if not raw[:8] == b"\x89PNG\r\n\x1a\n":
        raise HTTPException(400, "image is not a PNG")
    if len(raw) > _MAX_BYTES:
        raise HTTPException(413, "image too large")
    TRADE_IMG_DIR.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    logger.info("trade image stored: %s (%d bytes)", path.name, len(raw))
    return JSONResponse({"ok": True, "url": f"/trade-images/{key}.png"})


@router.get("/api/trade-images/{key}")
async def get_trade_image(key: str) -> JSONResponse:
    path = _path_for(key)
    exists = path.exists()
    return JSONResponse({"exists": exists,
                         "url": f"/trade-images/{key}.png" if exists else None})
