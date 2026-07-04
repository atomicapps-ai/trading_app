"""auth.py — login / logout for the single-password session gate.

GET  /login   -> login form (or straight redirect if auth is disabled)
POST /login   -> verify password, set the signed session cookie, redirect
GET  /logout  -> clear the cookie, back to /login
"""
from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from services.auth_service import (
    COOKIE_NAME, auth_enabled, check_password, make_session_token,
)
from services.settings_service import TEMPLATES_DIR

router = APIRouter()
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _safe_next(raw: str | None) -> str:
    """Only allow same-site relative redirects (no scheme/host) to avoid an
    open-redirect. Default to the dashboard."""
    if not raw:
        return "/"
    parts = urlsplit(raw)
    if parts.scheme or parts.netloc or not raw.startswith("/") or raw.startswith("//"):
        return "/"
    return raw


def _cookie_secure(request: Request) -> bool:
    # Behind Cloudflare Tunnel the app sees http from cloudflared even though
    # the client used https — honor X-Forwarded-Proto so the Secure flag is set
    # for real https clients without breaking local http.
    xf = request.headers.get("x-forwarded-proto", "").lower()
    return request.url.scheme == "https" or xf == "https"


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, next: str = "/", error: str | None = None):
    if not auth_enabled():
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"next": _safe_next(next), "error": error},
    )


@router.post("/login")
async def login_submit(request: Request,
                       password: str = Form(...),
                       next: str = Form("/")):
    dest = _safe_next(next)
    if not auth_enabled():
        return RedirectResponse("/", status_code=302)
    if not check_password(password):
        # Re-render with an error (303 so the browser GETs the form).
        return RedirectResponse(
            f"/login?next={dest}&error=Incorrect+password", status_code=303)
    resp = RedirectResponse(dest, status_code=303)
    resp.set_cookie(
        COOKIE_NAME, make_session_token(),
        httponly=True, samesite="lax", secure=_cookie_secure(request),
        max_age=30 * 24 * 3600, path="/",
    )
    return resp


@router.get("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(COOKIE_NAME, path="/")
    return resp
