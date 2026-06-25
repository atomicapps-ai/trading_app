"""company_service — cached ticker → company name lookup.

Resolves a human-readable company name for a symbol via yfinance, cached to disk so
we never refetch the same symbol. Used to label Kronos plans with the company name in
addition to the ticker. Best-effort: on any failure it returns the symbol unchanged.
"""
from __future__ import annotations

import json
import logging

from services.settings_service import DATA_DIR

logger = logging.getLogger(__name__)

_CACHE_PATH = DATA_DIR / "company_names.json"
_cache: dict[str, str] | None = None


def _load() -> dict[str, str]:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_CACHE_PATH.read_text()) if _CACHE_PATH.exists() else {}
        except Exception:  # noqa: BLE001
            _cache = {}
    return _cache


def _save() -> None:
    try:
        _CACHE_PATH.write_text(json.dumps(_cache))
    except Exception as exc:  # noqa: BLE001
        logger.debug("company-name cache save failed: %s", exc)


def get_name(symbol: str) -> str:
    """Return the company name for `symbol`, or the symbol itself if unknown."""
    sym = (symbol or "").upper()
    if not sym:
        return ""
    cache = _load()
    if sym in cache:
        return cache[sym] or sym
    name = sym
    try:
        import yfinance as yf
        info = yf.Ticker(sym).info
        name = info.get("longName") or info.get("shortName") or sym
    except Exception as exc:  # noqa: BLE001
        logger.debug("name lookup for %s failed: %s", sym, exc)
    cache[sym] = name
    _save()
    return name
