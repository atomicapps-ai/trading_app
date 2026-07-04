"""pwa.py — Progressive Web App plumbing so the app installs on phones/desktop.

Serves the web manifest, a minimal service worker, and the favicon at ROOT
paths (not under /static) so the service worker's scope is the whole app and
browsers find them where they expect.

IMPORTANT: the service worker deliberately does NOT cache API/data responses.
This is a live trading app — showing stale prices, positions, or a stale
pending queue would be dangerous. The SW exists only to satisfy installability;
all fetches go to the network.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse, Response

from services.settings_service import STATIC_DIR

router = APIRouter()

# Match the dark theme (static/app.css :root): base bg + topbar tint.
_BACKGROUND = "#0f1117"
_THEME = "#13151f"

_MANIFEST = {
    "name": "TradeAgent",
    "short_name": "TradeAgent",
    "description": "Multi-agent trading workflow manager",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "orientation": "any",
    "background_color": _BACKGROUND,
    "theme_color": _THEME,
    "icons": [
        {"src": "/static/icons/icon-192.png", "sizes": "192x192",
         "type": "image/png", "purpose": "any"},
        {"src": "/static/icons/icon-512.png", "sizes": "512x512",
         "type": "image/png", "purpose": "any"},
        {"src": "/static/icons/icon-512.png", "sizes": "512x512",
         "type": "image/png", "purpose": "maskable"},
    ],
}

_SERVICE_WORKER = """\
// TradeAgent service worker — installability only.
// Deliberately network-only: a trading app must never serve stale prices,
// positions, or a stale pending queue from cache.
self.addEventListener('install', (e) => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (event) => {
  // Pass through to the network. No caching of app data.
  event.respondWith(fetch(event.request));
});
"""


@router.get("/manifest.webmanifest")
async def manifest() -> JSONResponse:
    return JSONResponse(_MANIFEST, media_type="application/manifest+json")


@router.get("/service-worker.js")
async def service_worker() -> Response:
    return Response(
        _SERVICE_WORKER,
        media_type="application/javascript",
        # Allow a root-scoped SW even though it's served from a route.
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


@router.get("/favicon.ico")
async def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "icons" / "favicon-32.png",
                        media_type="image/png")
