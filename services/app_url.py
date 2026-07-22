"""app_url.py — resolve the base URL the app is actually reachable at.

The app is served locally (``http://127.0.0.1:5000``) and exposed publicly via a
Cloudflare tunnel (``https://app.tindex.ai``). Either may be the only one that
works at a given moment (tunnel down → localhost only; off-box → tunnel only).
This probes ``/health`` on each candidate and returns the first that answers, so
scripts and instructions don't hard-code the wrong one.

Order tried:
  1. ``settings.app.public_base_url`` (from PUBLIC_BASE_URL env), else the
     default public origin ``https://app.tindex.ai``
  2. ``http://127.0.0.1:<port>`` and ``http://localhost:<port>``

Usage (code):   from services.app_url import resolve_base_url
Usage (shell):  python -m scripts.app_url
"""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

DEFAULT_PUBLIC = "https://app.tindex.ai"


def candidates(settings=None) -> list[str]:
    """Ordered, de-duped base URLs to try (public origin first, then local)."""
    if settings is None:
        from services.settings_service import get_settings
        settings = get_settings()
    port = getattr(settings.app, "port", 5000) or 5000
    public = (getattr(settings.app, "public_base_url", "") or "").rstrip("/") or DEFAULT_PUBLIC
    out: list[str] = []
    for base in (public, f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
        base = base.rstrip("/")
        if base and base not in out:
            out.append(base)
    return out


def probe(base: str, timeout: float = 2.5) -> bool:
    """True if GET {base}/health returns 200."""
    try:
        r = httpx.get(f"{base}/health", timeout=timeout, follow_redirects=True)
        return r.status_code == 200
    except Exception as e:  # noqa: BLE001
        logger.debug("app_url probe failed for %s: %s", base, e)
        return False


def resolve_base_url(settings=None) -> tuple[str, bool]:
    """Return (base_url, reachable). The first candidate that answers /health;
    if none answer, return the local candidate with reachable=False so callers
    still have a usable default."""
    cands = candidates(settings)
    for base in cands:
        if probe(base):
            return base, True
    # none reachable → prefer the local fallback (last candidate) as the guess
    return cands[-1], False
