"""auth_middleware.py — gate every request behind the session cookie.

Pass-through when auth is disabled (no APP_AUTH_PASSWORD), so local dev is
unchanged. When enabled, every request must carry a valid session cookie
except a small allow-list (health check, the login page itself, static
assets, favicon, PWA manifest). Unauthenticated:
  - browser navigation (Accept: text/html, non-HTMX) -> 302 to /login?next=…
  - everything else (API / HTMX / JSON) -> 401
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from services.auth_service import COOKIE_NAME, auth_enabled, verify_session_token

# Prefixes/paths reachable without a session.
_ALLOW_PREFIXES = ("/static/",)
_ALLOW_EXACT = {
    "/health", "/login", "/logout", "/favicon.ico",
    "/manifest.webmanifest", "/service-worker.js",
}


def _is_allowlisted(path: str) -> bool:
    if path in _ALLOW_EXACT:
        return True
    return any(path.startswith(p) for p in _ALLOW_PREFIXES)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not auth_enabled() or _is_allowlisted(request.url.path):
            return await call_next(request)

        token = request.cookies.get(COOKIE_NAME)
        if verify_session_token(token):
            return await call_next(request)

        # Unauthenticated. Redirect real browser navigations to the login
        # page; answer API/HTMX/programmatic calls with a clean 401 so they
        # don't render a login page inside a fragment.
        accept = request.headers.get("accept", "")
        is_hx = request.headers.get("hx-request", "").lower() == "true"
        wants_html = "text/html" in accept and not is_hx
        if wants_html:
            nxt = request.url.path
            if request.url.query:
                nxt += "?" + request.url.query
            from urllib.parse import quote
            return RedirectResponse(f"/login?next={quote(nxt, safe='')}",
                                    status_code=302)
        resp = JSONResponse({"detail": "authentication required"}, status_code=401)
        if is_hx:
            # Tell HTMX to bounce the whole page to login rather than swap a 401.
            resp.headers["HX-Redirect"] = "/login"
        return resp
