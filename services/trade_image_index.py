"""trade_image_index.py — version-aware cache index for per-trade chart images.

Images live at ``data/trade_images/<key>.png`` (generated in-browser, Option B).
This tracks WHICH generator version produced each one, so a row can be flagged
**outdated** when the renderer changes — and regenerated on demand instead of
being redrawn every time.

Bump ``IMAGE_GEN_VERSION`` whenever the chart-rendering logic in
``static/trade_images.js`` changes in a way that should invalidate old PNGs.
Existing images then show as stale (thumbnail + "outdated" regenerate control)
until re-generated; up-to-date ones are never redrawn.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from services.settings_service import DATA_DIR

logger = logging.getLogger(__name__)

# ⬆ Bump this when static/trade_images.js rendering changes materially.
IMAGE_GEN_VERSION = 1

TRADE_IMG_DIR: Path = DATA_DIR / "trade_images"
_INDEX_PATH: Path = TRADE_IMG_DIR / "_index.json"


def _load_index() -> dict:
    try:
        return json.loads(_INDEX_PATH.read_text()) if _INDEX_PATH.exists() else {}
    except Exception:  # noqa: BLE001
        return {}


def record(key: str) -> None:
    """Stamp ``key`` as generated at the current version. Best-effort."""
    try:
        TRADE_IMG_DIR.mkdir(parents=True, exist_ok=True)
        idx = _load_index()
        idx[key] = IMAGE_GEN_VERSION
        _INDEX_PATH.write_text(json.dumps(idx))
    except Exception as exc:  # noqa: BLE001
        logger.warning("trade_image_index.record failed for %s: %s", key, exc)


def status(key: str | None) -> dict:
    """Return {exists, stale, url, version} for a trade-image key.

    ``stale`` is True when a PNG exists but was made by an older generator
    version (or predates the index) — i.e. it should be regenerated.
    """
    if not key:
        return {"exists": False, "stale": False, "url": None, "version": None}
    exists = (TRADE_IMG_DIR / f"{key}.png").exists()
    if not exists:
        return {"exists": False, "stale": False, "url": None, "version": None}
    ver = _load_index().get(key)
    stale = (ver != IMAGE_GEN_VERSION)
    return {
        "exists": True,
        "stale": stale,
        "url": f"/trade-images/{key}.png",
        "version": ver,
    }
