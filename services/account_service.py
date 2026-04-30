"""account_service.py — multi-account broker credential registry.

Replaces the single-account .env model. Each ``broker_accounts`` row is
one (provider, account_type, credentials) tuple. Exactly one row has
``is_active=1`` at any time; that's the adapter the app uses.

Boot sequence
-------------
1. ``ensure_seeded_from_env()`` runs once at startup.
2. If the table is empty AND ``ALPACA_API_KEY`` / ``ALPACA_API_SECRET``
   are set in the environment, we create one paper account row.
3. If ``TS_CLIENT_ID`` / ``TS_CLIENT_SECRET`` / ``TS_REFRESH_TOKEN`` are
   set, we also create one TradeStation row at the configured tier
   (sim/live based on TS_SIM).
4. The first row created is set active.

Security
--------
Credentials are stored plaintext. This matches the existing .env model:
single-user local tool, DB file is gitignored, app binds to
localhost/Tailscale. The DB carries the same trust level as .env.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone

import aiosqlite

from services.db_service import DB_PATH

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    s = _SLUG_RE.sub("-", text.lower()).strip("-")
    return s or "account"


def _row_to_dict(row: aiosqlite.Row) -> dict:
    d = {k: row[k] for k in row.keys()}
    if d.get("extra_json"):
        try:
            d["extra"] = json.loads(d["extra_json"])
        except json.JSONDecodeError:
            d["extra"] = {}
    else:
        d["extra"] = {}
    d.pop("extra_json", None)
    d["is_active"] = bool(d.get("is_active"))
    return d


def _redact(d: dict) -> dict:
    """Masked copy — for any caller that doesn't strictly need the secret."""
    out = dict(d)
    if out.get("key_id"):
        kid = out["key_id"]
        out["key_id_masked"] = (kid[:4] + "…" + kid[-4:]) if len(kid) > 8 else "…"
    if out.get("secret"):
        out["secret"] = "•" * 8
    return out


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #


async def list_accounts() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM broker_accounts "
            "ORDER BY is_active DESC, account_type, provider, label"
        )
        rows = await cur.fetchall()
    return [_row_to_dict(r) for r in rows]


async def list_accounts_redacted() -> list[dict]:
    return [_redact(a) for a in await list_accounts()]


async def get_account(slug: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM broker_accounts WHERE slug = ?", (slug,),
        )
        row = await cur.fetchone()
    return _row_to_dict(row) if row else None


async def get_active_account() -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM broker_accounts WHERE is_active = 1 LIMIT 1"
        )
        row = await cur.fetchone()
    return _row_to_dict(row) if row else None


async def create_account(
    *,
    label: str,
    provider: str,
    account_type: str,
    key_id: str,
    secret: str,
    slug: str | None = None,
    extra: dict | None = None,
    activate: bool = False,
) -> dict:
    if provider not in ("alpaca", "tradestation"):
        raise ValueError(f"unknown provider: {provider!r}")
    if account_type not in ("paper", "live"):
        raise ValueError(f"account_type must be 'paper' or 'live', got {account_type!r}")
    if not key_id.strip() or not secret.strip():
        raise ValueError("key_id and secret are required")

    slug = slug or _unique_slug(label, provider, account_type)
    async with aiosqlite.connect(DB_PATH) as db:
        # Slug collision guard. Append a numeric suffix until unique.
        existing = await _slugs(db)
        base = slug
        i = 2
        while slug in existing:
            slug = f"{base}-{i}"
            i += 1
        ts = _now()
        await db.execute(
            """
            INSERT INTO broker_accounts
                (slug, label, provider, account_type, key_id, secret,
                 extra_json, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (slug, label, provider, account_type, key_id, secret,
             json.dumps(extra) if extra else None, ts, ts),
        )
        await db.commit()
    if activate:
        await set_active(slug)
    return await get_account(slug)  # type: ignore[return-value]


async def update_account(
    slug: str,
    *,
    label: str | None = None,
    key_id: str | None = None,
    secret: str | None = None,
    extra: dict | None = None,
    account_type: str | None = None,
    provider: str | None = None,
) -> bool:
    """Update one row. All fields are optional; only the ones provided
    are written. ``account_type`` and ``provider`` ARE editable — needed
    when the user mis-classified a row at create time (e.g. created a
    "paper" account with live keys). The active adapter is NOT rebuilt
    here; callers (the broker router) own that side-effect after a
    successful update."""
    fields: list[tuple[str, object]] = []
    if label is not None:
        fields.append(("label", label))
    if key_id is not None:
        fields.append(("key_id", key_id))
    if secret is not None:
        fields.append(("secret", secret))
    if extra is not None:
        fields.append(("extra_json", json.dumps(extra)))
    if account_type is not None:
        if account_type not in ("paper", "live"):
            raise ValueError(
                f"account_type must be 'paper' or 'live', got {account_type!r}"
            )
        fields.append(("account_type", account_type))
    if provider is not None:
        if provider not in ("alpaca", "tradestation"):
            raise ValueError(f"unknown provider: {provider!r}")
        fields.append(("provider", provider))
    if not fields:
        return False
    fields.append(("updated_at", _now()))
    sql = ", ".join(f"{k} = ?" for k, _ in fields)
    params = [v for _, v in fields] + [slug]
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            f"UPDATE broker_accounts SET {sql} WHERE slug = ?", params,
        )
        await db.commit()
        return cur.rowcount > 0


async def delete_account(slug: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        # Refuse if this is the last active row — leave the user with at
        # least one account so the broker layer doesn't end up unconfigured.
        cur = await db.execute(
            "SELECT is_active FROM broker_accounts WHERE slug = ?", (slug,),
        )
        row = await cur.fetchone()
        if row is None:
            return False
        was_active = bool(row[0])
        await db.execute("DELETE FROM broker_accounts WHERE slug = ?", (slug,))
        if was_active:
            # Promote the most recently updated row to active so we always
            # have one selected. If nothing remains, the registry is empty.
            await db.execute(
                "UPDATE broker_accounts SET is_active = 1, updated_at = ? "
                "WHERE id = (SELECT id FROM broker_accounts "
                "ORDER BY updated_at DESC LIMIT 1)",
                (_now(),),
            )
        await db.commit()
    return True


async def set_active(slug: str) -> bool:
    """Atomically: clear is_active on every other row, set on the target."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Verify target exists first
        cur = await db.execute(
            "SELECT id FROM broker_accounts WHERE slug = ?", (slug,),
        )
        if not await cur.fetchone():
            return False
        ts = _now()
        await db.execute(
            "UPDATE broker_accounts SET is_active = 0, updated_at = ? "
            "WHERE is_active = 1",
            (ts,),
        )
        await db.execute(
            "UPDATE broker_accounts SET is_active = 1, updated_at = ? "
            "WHERE slug = ?",
            (ts, slug),
        )
        await db.commit()
    return True


async def record_connect(slug: str, *, error: str | None = None) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        if error is None:
            await db.execute(
                "UPDATE broker_accounts SET last_connected_at = ?, "
                "last_error = NULL WHERE slug = ?",
                (_now(), slug),
            )
        else:
            await db.execute(
                "UPDATE broker_accounts SET last_error = ? WHERE slug = ?",
                (error[:500], slug),
            )
        await db.commit()


# --------------------------------------------------------------------------- #
# Env seeding (run once at startup)
# --------------------------------------------------------------------------- #


async def ensure_seeded_from_env() -> None:
    """If the registry is empty, create rows from existing .env credentials.

    Idempotent. Runs after ``db_service.ensure_tables()`` in app lifespan.
    Doesn't touch the registry once any row exists — letting the user own
    the registry via UI from that point on.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM broker_accounts")
        row = await cur.fetchone()
        count = int(row[0]) if row else 0
    if count > 0:
        return

    seeded: list[str] = []

    # Alpaca paper — most common starting state. Default ALPACA_PAPER=true
    # in the env-seed flow regardless of the env var, since seeding to
    # paper is the safe default; the user can flip to a separate live
    # row via UI.
    alpaca_key = os.getenv("ALPACA_TRADING_KEY_ID") or os.getenv("ALPACA_API_KEY")
    alpaca_secret = os.getenv("ALPACA_TRADING_SECRET") or os.getenv("ALPACA_API_SECRET")
    if alpaca_key and alpaca_secret:
        is_live = os.getenv("ALPACA_PAPER", "true").lower() == "false"
        acct_type = "live" if is_live else "paper"
        try:
            await create_account(
                label=f"Alpaca {acct_type.capitalize()} (from .env)",
                provider="alpaca",
                account_type=acct_type,
                key_id=alpaca_key,
                secret=alpaca_secret,
                activate=True,  # first row -> active
            )
            seeded.append(f"alpaca/{acct_type}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("seed alpaca from env failed: %s", exc)

    # TradeStation — only seed if the full triple is present.
    ts_id = os.getenv("TS_CLIENT_ID")
    ts_secret = os.getenv("TS_CLIENT_SECRET")
    ts_refresh = os.getenv("TS_REFRESH_TOKEN")
    if ts_id and ts_secret and ts_refresh:
        ts_sim = os.getenv("TS_SIM", "true").lower() != "false"
        acct_type = "paper" if ts_sim else "live"
        ts_account_id = os.getenv("TS_ACCOUNT_ID", "")
        try:
            await create_account(
                label=f"TradeStation {acct_type.capitalize()} (from .env)",
                provider="tradestation",
                account_type=acct_type,
                key_id=ts_id,
                secret=ts_secret,
                extra={
                    "refresh_token": ts_refresh,
                    "account_id": ts_account_id,
                },
                # Only activate TS if Alpaca wasn't seeded (Alpaca wins the
                # default — it's the documented paper default).
                activate=not seeded,
            )
            seeded.append(f"tradestation/{acct_type}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("seed tradestation from env failed: %s", exc)

    if seeded:
        logger.info("broker_accounts: seeded from .env -> %s", ", ".join(seeded))
    else:
        logger.info(
            "broker_accounts: no .env credentials found to seed; "
            "add accounts via /broker"
        )


# --------------------------------------------------------------------------- #
# Internal
# --------------------------------------------------------------------------- #


def _unique_slug(label: str, provider: str, account_type: str) -> str:
    return slugify(f"{provider}-{account_type}-{label}")


async def _slugs(db: aiosqlite.Connection) -> set[str]:
    cur = await db.execute("SELECT slug FROM broker_accounts")
    rows = await cur.fetchall()
    return {r[0] for r in rows}
