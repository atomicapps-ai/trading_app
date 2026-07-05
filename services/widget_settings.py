"""widget_settings.py — per-user overrides for dashboard widgets and
chart-using surfaces. Backed by the ``user_widget_settings`` SQLite table.

Single-user local app: all reads/writes use ``user_id="default"`` until
multi-user lands. Values are stored as JSON-encoded strings so we can
hold ints, floats, bools, lists, dicts in the same column.

Read order (resolved in ``get_with_default``):
    1. user override (this table)
    2. caller-supplied default
    3. None

Public API
----------
    get(user_id, widget_id, key) -> Any | None
    get_with_default(user_id, widget_id, key, default) -> Any
    get_all(user_id, widget_id) -> dict[str, Any]
    set_(user_id, widget_id, key, value) -> None
    delete(user_id, widget_id, key) -> None
    reset_widget(user_id, widget_id) -> None
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import aiosqlite
from services import db as _dbmod

from services.db_service import DB_PATH

logger = logging.getLogger(__name__)

DEFAULT_USER = "default"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #


async def get(user_id: str, widget_id: str, key: str) -> Any | None:
    async with _dbmod.connect() as db:
        cur = await db.execute(
            "SELECT setting_value FROM user_widget_settings "
            "WHERE user_id = ? AND widget_id = ? AND setting_key = ?",
            (user_id, widget_id, key),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            logger.warning(
                "widget_settings: bad JSON in %s/%s/%s — returning raw string",
                user_id, widget_id, key,
            )
            return row[0]


async def get_with_default(
    user_id: str, widget_id: str, key: str, default: Any,
) -> Any:
    val = await get(user_id, widget_id, key)
    return default if val is None else val


async def get_all(user_id: str, widget_id: str) -> dict[str, Any]:
    """Return every setting saved for (user, widget) as a dict."""
    async with _dbmod.connect() as db:
        cur = await db.execute(
            "SELECT setting_key, setting_value FROM user_widget_settings "
            "WHERE user_id = ? AND widget_id = ?",
            (user_id, widget_id),
        )
        rows = await cur.fetchall()
    out: dict[str, Any] = {}
    for k, v in rows:
        try:
            out[k] = json.loads(v)
        except json.JSONDecodeError:
            out[k] = v
    return out


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #


async def set_(user_id: str, widget_id: str, key: str, value: Any) -> None:
    """Upsert a setting. Value is JSON-encoded for type fidelity."""
    payload = json.dumps(value, default=str)
    async with _dbmod.connect() as db:
        await db.execute(
            """
            INSERT INTO user_widget_settings
                   (user_id, widget_id, setting_key, setting_value, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, widget_id, setting_key) DO UPDATE SET
                setting_value = excluded.setting_value,
                updated_at    = excluded.updated_at
            """,
            (user_id, widget_id, key, payload, _now()),
        )
        await db.commit()


async def set_many(
    user_id: str, widget_id: str, kv: dict[str, Any],
) -> None:
    """Upsert multiple keys atomically."""
    if not kv:
        return
    now = _now()
    rows = [
        (user_id, widget_id, k, json.dumps(v, default=str), now)
        for k, v in kv.items()
    ]
    async with _dbmod.connect() as db:
        await db.executemany(
            """
            INSERT INTO user_widget_settings
                   (user_id, widget_id, setting_key, setting_value, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, widget_id, setting_key) DO UPDATE SET
                setting_value = excluded.setting_value,
                updated_at    = excluded.updated_at
            """,
            rows,
        )
        await db.commit()


async def delete(user_id: str, widget_id: str, key: str) -> None:
    async with _dbmod.connect() as db:
        await db.execute(
            "DELETE FROM user_widget_settings "
            "WHERE user_id = ? AND widget_id = ? AND setting_key = ?",
            (user_id, widget_id, key),
        )
        await db.commit()


async def reset_widget(user_id: str, widget_id: str) -> None:
    """Drop every saved setting for this widget — falls back to defaults."""
    async with _dbmod.connect() as db:
        await db.execute(
            "DELETE FROM user_widget_settings "
            "WHERE user_id = ? AND widget_id = ?",
            (user_id, widget_id),
        )
        await db.commit()
