"""ntfy_service.py — phone push notifications via ntfy.sh.

Single entry point: ``push()``. Every caller — Lock 1 scout alerts,
armed alerts, fill confirmations, test injections — funnels through
this function. It is fire-and-forget: any HTTP failure is logged at
WARN and swallowed. The alerting path must never crash because the
push provider is down.

Topic + server come from ``settings.ntfy``. Subscribe on your phone via
the ntfy app to ``settings.ntfy.topic`` to receive the pushes.

Subscription URL (paste into the ntfy mobile app):
    https://ntfy.sh/<topic>
"""
from __future__ import annotations

import logging
from typing import Iterable

import httpx

from services.settings_service import get_settings

logger = logging.getLogger(__name__)


_VALID_PRIORITIES = {"min", "low", "default", "high", "urgent"}

# ntfy JSON publish API uses integer priorities 1-5 instead of strings.
# https://docs.ntfy.sh/publish/#message-priority
_PRIORITY_TO_INT = {"min": 1, "low": 2, "default": 3, "high": 4, "urgent": 5}


async def push(
    title: str,
    body: str,
    *,
    priority: str = "default",
    tags: Iterable[str] | None = None,
    click_url: str | None = None,
    actions: list[dict] | None = None,
    timeout_seconds: float = 5.0,
) -> bool:
    """Send a push notification. Returns True on success, False on any failure.

    ``actions`` is a list of ntfy action buttons (max 3). Each is a dict in
    ntfy's JSON shape, e.g.::

        {"action": "view", "label": "Open plan", "url": "https://…", "clear": true}
        {"action": "http", "label": "Approve", "method": "POST", "url": "https://…",
         "headers": {"Content-Type": "application/x-www-form-urlencoded"},
         "body": "action=approve", "clear": true}

    See https://docs.ntfy.sh/publish/#action-buttons. ntfy silently ignores
    the action array beyond the third entry, so callers should cap at 3.

    Never raises — alert recording must not break because ntfy is down.
    """
    settings = get_settings()
    ntfy = settings.ntfy

    if not getattr(ntfy, "enabled", True):
        logger.debug("ntfy disabled in settings; skipping push: %s", title)
        return False

    if priority not in _VALID_PRIORITIES:
        logger.warning("ntfy: invalid priority %r, falling back to 'default'", priority)
        priority = "default"

    # Use the JSON publish API (POST /) instead of header-based metadata
    # so non-ASCII characters (e.g. "·") in title/body Just Work. httpx
    # encodes HTTP headers as ASCII and rejects raw Unicode header values.
    payload: dict = {
        "topic":    ntfy.topic,
        "title":    title,
        "message":  body,
        "priority": _PRIORITY_TO_INT[priority],
    }
    if tags:
        payload["tags"] = list(tags)
    if click_url:
        payload["click"] = click_url
    if actions:
        # ntfy caps at 3 action buttons; extra entries are ignored server-side
        # but we trim explicitly so behaviour is predictable.
        payload["actions"] = list(actions)[:3]

    url = ntfy.server.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
        logger.info("ntfy push sent: title=%r priority=%s", title, priority)
        return True
    except Exception as exc:  # noqa: BLE001 — we deliberately swallow every error
        logger.warning("ntfy push failed (%s): %s", type(exc).__name__, exc)
        return False
