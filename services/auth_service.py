"""auth_service.py — lightweight single-password session auth.

The app was built as a single-user LOCAL tool with no login. Exposing it to the
internet (Cloudflare Tunnel, traveling) needs a gate, because it can place real
orders. This provides that gate with zero new dependencies: a shared password
plus an HMAC-signed session cookie (stdlib ``hmac``/``hashlib``).

Design:
- Auth is OFF unless ``APP_AUTH_PASSWORD`` is set, so local dev is unchanged.
- The session cookie is ``<b64(payload)>.<hmac_sha256(payload)>`` where payload
  is ``{"exp": <unix>}``. Tamper-proof (HMAC) and self-expiring (exp).
- The signing secret is ``APP_SECRET_KEY`` if set, else derived deterministically
  from the password so sessions survive restarts without extra config.

This is intentionally the BACKSTOP layer for a Cloudflare-Access deployment
(Access does SSO/MFA at the edge; this stops the app being open if reached
directly). Cloudflare Access JWT verification can layer on top later.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time

logger = logging.getLogger(__name__)

COOKIE_NAME = "ta_session"
_DEFAULT_TTL_SECONDS = 30 * 24 * 3600  # 30 days — single-user convenience


def _password() -> str:
    return os.environ.get("APP_AUTH_PASSWORD", "").strip()


def auth_enabled() -> bool:
    """True when a password is configured. When False the middleware is a
    pass-through and the app behaves exactly as the old local-only tool."""
    return bool(_password())


def _secret() -> bytes:
    explicit = os.environ.get("APP_SECRET_KEY", "").strip()
    if explicit:
        return explicit.encode("utf-8")
    # Derive from the password so cookies stay valid across restarts without
    # requiring a second env var. Namespaced so it isn't the raw password hash.
    return hashlib.sha256(("tradeagent-session::" + _password()).encode()).digest()


def check_password(candidate: str) -> bool:
    """Constant-time compare against APP_AUTH_PASSWORD."""
    pw = _password()
    if not pw:
        return False
    return hmac.compare_digest(candidate.encode("utf-8"), pw.encode("utf-8"))


def _sign(payload: bytes) -> str:
    return hmac.new(_secret(), payload, hashlib.sha256).hexdigest()


def make_session_token(ttl_seconds: int = _DEFAULT_TTL_SECONDS,
                       now: float | None = None) -> str:
    """Signed, self-expiring session token. ``now`` is injectable for tests."""
    exp = int((now if now is not None else time.time()) + ttl_seconds)
    payload = json.dumps({"exp": exp}, separators=(",", ":")).encode("utf-8")
    b64 = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    return f"{b64}.{_sign(payload)}"


def verify_session_token(token: str | None, now: float | None = None) -> bool:
    if not token or "." not in token:
        return False
    b64, sig = token.rsplit(".", 1)
    try:
        pad = "=" * (-len(b64) % 4)
        payload = base64.urlsafe_b64decode(b64 + pad)
    except Exception:  # noqa: BLE001
        return False
    if not hmac.compare_digest(sig, _sign(payload)):
        return False
    try:
        data = json.loads(payload)
        exp = int(data["exp"])
    except Exception:  # noqa: BLE001
        return False
    return (now if now is not None else time.time()) < exp
