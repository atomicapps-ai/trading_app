"""alert_service.py — strategy notifications backing the dashboard banner.

A thin layer over the ``dl_alerts`` table. Records detection events
emitted by strategies (today: DL — Double Lock) so the dashboard can
poll for fresh notifications without scraping pending_approvals.

Alert kinds
-----------
``lock1_scouted``   — 10:00 ET scout: candle 1 + regime cleared, watch 10:30
``armed``           — 10:30 ET fire: full pattern matched, TradePlan in /pending
``filled``          — broker filled the entry order (Phase 6 — not wired yet)
``closed``          — position flattened by close_at_time or manual exit
``test``            — operator-injected via /api/alerts/test for verification

Why a separate table
--------------------
``pending_approvals`` is the *plan*; ``dl_alerts`` is the *event stream*.
A single plan can generate multiple alert rows (lock1 → armed → filled →
closed) without distorting the plans table. Acknowledged alerts stay in
the table for the audit trail; the UI just filters them out by default.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Iterable, Literal

import aiosqlite
from services import db as _dbmod

from services.db_service import DB_PATH

logger = logging.getLogger(__name__)

AlertKind = Literal[
    "lock1_scouted",        # 10:00 ET DL early-warning
    "armed",                 # plan passed gates, awaiting ack
    "filled",                # entry order filled
    "closed",                # position closed (manual or auto close-at-time)
    "rejected",              # plan blocked by compliance / risk gate (no phone push)
    "manual_take_profit",    # operator-tagged profit take
    "manual_edit",           # operator updated plan levels
    "digest",                # end-of-day summary, single push per day
    "test",                  # synthetic injector
]

# Alert kinds that should NEVER fire a phone push — they only land on the
# dashboard banner. Used to give the operator visibility ("system saw N
# plans today, rejected M of them") without ringing the phone for every
# discarded signal.
_NO_PUSH_KINDS = {"rejected"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Phone-push formatting helpers
# --------------------------------------------------------------------------- #


def _resolve_base_url(s: Any) -> str:
    """Public origin for deep links. Prefer the reachable public URL; fall
    back to the tailnet host (only resolves on the tailnet with MagicDNS)."""
    base = (getattr(s.app, "public_base_url", None) or "").rstrip("/")
    if base:
        return base
    host = getattr(s.app, "tailscale_hostname", None) or "127.0.0.1"
    return f"http://{host}:{s.app.port}"


def _fmt_price(v: Any) -> str | None:
    """'$128.40' from a number, else None."""
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return None


def _fmt_valid_until(v: Any) -> str:
    """'10:45 ET' from an iso8601 deadline; pass through short tokens; '' on
    anything unparseable."""
    if not v or not isinstance(v, str):
        return ""
    try:
        from zoneinfo import ZoneInfo
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        et = dt.astimezone(ZoneInfo("America/New_York"))
        return f"{et:%H:%M} ET"
    except Exception:  # noqa: BLE001 — non-iso value, show nothing
        return ""


def _pct_from_entry(price: Any, entry: Any, direction: str | None) -> str:
    """Signed % move from entry to price, oriented so a favourable move
    (toward a long's TP, or a short's TP) reads positive. Empty on bad input."""
    try:
        p, e = float(price), float(entry)
        if e == 0:
            return ""
        raw = (p - e) / e * 100.0
        return f"  ({raw:+.1f}%)"
    except (TypeError, ValueError):
        return ""


def _rich_armed_body(
    strategy: str,
    direction: str | None,
    payload: dict[str, Any],
) -> str:
    """Multi-line trade card for an ARMED alert. Everything the operator
    needs to decide is on the notification itself — entry, protective stop,
    targets, sizing, risk, R:R, conviction — so they rarely need to open
    the app to triage."""
    entry = payload.get("entry_price")
    stop = payload.get("stop_price")
    tps = payload.get("tp_prices") or []
    lines: list[str] = []

    dir_label = (direction or "").upper()
    lines.append(f"{dir_label} · {strategy}".strip(" ·"))

    e_str = _fmt_price(entry)
    if e_str:
        lines.append(f"Entry  {e_str}")
    s_str = _fmt_price(stop)
    if s_str:
        lines.append(f"Stop   {s_str}{_pct_from_entry(stop, entry, direction)}")
    for i, tp in enumerate(tps[:2], start=1):
        t_str = _fmt_price(tp)
        if t_str:
            lines.append(f"TP{i}    {t_str}{_pct_from_entry(tp, entry, direction)}")

    rr1, rr2 = payload.get("rr_tp1"), payload.get("rr_tp2")
    if rr1 or rr2:
        rr_bits = [str(x) for x in (rr1, rr2) if x]
        lines.append(f"R:R    {' / '.join(rr_bits)}")

    shares = payload.get("shares")
    notional = _fmt_price(payload.get("notional_usd"))
    if shares or notional:
        size = f"Size   {shares or '?'} sh"
        if notional:
            size += f" · {notional}"
        lines.append(size)

    risk = _fmt_price(payload.get("risk_usd"))
    if risk:
        lines.append(f"Risk   {risk}")

    conv = payload.get("conviction")
    if conv is not None:
        try:
            lines.append(f"Conv   {float(conv):.0%}")
        except (TypeError, ValueError):
            pass

    valid = _fmt_valid_until(payload.get("valid_until"))
    if valid:
        lines.append(f"Valid  {valid}")

    return "\n".join(lines)


def _build_actions(
    kind: str,
    plan_id: str | None,
    base: str,
    mode: str | None,
) -> list[dict]:
    """Notification action buttons (max 3). ARMED plans get a deep link to
    the plan page and — in PAPER mode only — a one-tap Approve that POSTs the
    ack straight to the pipeline. Live mode deliberately omits Approve: the
    human ack must happen on the plan screen where the full setup is visible
    (CLAUDE.md non-negotiable)."""
    actions: list[dict] = []
    if kind == "armed" and plan_id:
        actions.append({
            "action": "view",
            "label": "Open plan ↗",
            "url": f"{base}/pending/{plan_id}",
            "clear": False,
        })
        if (mode or "").lower() == "paper":
            actions.append({
                "action": "http",
                "label": "Approve ✓",
                "method": "POST",
                "url": f"{base}/pending/{plan_id}/ack",
                "headers": {"Content-Type": "application/x-www-form-urlencoded"},
                "body": "action=approve",
                "clear": True,
            })
    return actions


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #


async def record_alert(
    *,
    kind: AlertKind,
    title: str,
    strategy: str = "double_lock",
    symbol: str | None = None,
    direction: str | None = None,
    plan_id: str | None = None,
    body: str | None = None,
    payload: dict[str, Any] | None = None,
) -> int:
    """Append one alert row. Returns the new row id."""
    payload_json = json.dumps(payload) if payload else None
    async with _dbmod.connect() as db:
        cur = await db.execute(
            """
            INSERT INTO dl_alerts
                (ts, kind, strategy, symbol, direction, plan_id,
                 title, body, payload_json, acknowledged_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (_now(), kind, strategy, symbol, direction, plan_id,
             title, body, payload_json),
        )
        await db.commit()
        new_id = cur.lastrowid or 0
    logger.info(
        "alert recorded: id=%s kind=%s strategy=%s symbol=%s",
        new_id, kind, strategy, symbol,
    )

    # Skip phone push for kinds in _NO_PUSH_KINDS — they only land on
    # the dashboard banner so the operator can see "system rejected
    # these plans" without ringing the phone for every discarded signal.
    if kind in _NO_PUSH_KINDS:
        return new_id

    # Fire-and-forget phone push. Never raises — ntfy_service swallows
    # all errors so a flaky push provider can't break alert recording.
    try:
        from services import ntfy_service
        from services.settings_service import get_settings

        s = get_settings()
        # Map alert kind → ntfy priority. Lock1 is informational; armed +
        # filled are actionable; closed/test are quiet.
        priority_by_kind: dict[str, str] = {
            "lock1_scouted":      "default",
            "armed":              s.ntfy.priority_map.pending_approval,  # "high"
            "filled":             s.ntfy.priority_map.fill_received,     # "default"
            "closed":             "low",
            "manual_take_profit": "default",
            "manual_edit":        "low",
            "digest":             "default",
            "test":               "low",
        }
        priority = priority_by_kind.get(kind, "default")

        # Tag pulls a relevant emoji on the phone (chart_increasing for
        # bullish armed, etc.). ntfy renders these as small icons.
        tag_by_kind: dict[str, str] = {
            "lock1_scouted":      "eyes",
            "armed":              "chart_increasing" if direction == "long" else "chart_decreasing",
            "filled":             "white_check_mark",
            "closed":             "checkered_flag",
            "manual_take_profit": "moneybag",
            "manual_edit":        "pencil",
            "digest":             "newspaper",
            "test":               "test_tube",
        }
        tags = [tag_by_kind.get(kind, "bell")]

        # Click URL deep-links to the right page. Armed alerts go to the
        # specific pending approval; everything else lands on the dashboard.
        # Prefer the public origin (e.g. https://app.tindex.ai) when deployed
        # so tapping the push opens the real site, not an unreachable LAN host.
        base = _resolve_base_url(s)
        if kind == "armed" and plan_id:
            click_url = f"{base}/pending/{plan_id}"
        else:
            click_url = f"{base}/"

        # Richer body: ARMED plans get a full trade card built from the
        # payload (entry/stop/TP/R:R/size/risk/conviction). Other kinds keep
        # whatever the caller passed. Action buttons (Open plan / paper-only
        # Approve) come from _build_actions.
        payload = payload or {}
        if kind == "armed":
            push_body = _rich_armed_body(strategy, direction, payload)
        else:
            push_body = body or f"{kind} · {symbol or strategy}"

        actions = _build_actions(kind, plan_id, base, payload.get("mode"))

        await ntfy_service.push(
            title=title,
            body=push_body,
            priority=priority,
            tags=tags,
            click_url=click_url,
            actions=actions,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("ntfy hook failed (alert recorded successfully): %s", exc)

    return new_id


async def acknowledge(alert_ids: int | Iterable[int]) -> int:
    """Mark one or more alerts as acknowledged. Returns rows updated."""
    if isinstance(alert_ids, int):
        ids = [alert_ids]
    else:
        ids = list(alert_ids)
    if not ids:
        return 0
    placeholders = ",".join("?" * len(ids))
    async with _dbmod.connect() as db:
        cur = await db.execute(
            f"UPDATE dl_alerts SET acknowledged_at = ? "
            f"WHERE id IN ({placeholders}) AND acknowledged_at IS NULL",
            (_now(), *ids),
        )
        await db.commit()
        return cur.rowcount


async def acknowledge_all_unread() -> int:
    """Bulk-ack — used by the "dismiss all" affordance on the banner."""
    async with _dbmod.connect() as db:
        cur = await db.execute(
            "UPDATE dl_alerts SET acknowledged_at = ? "
            "WHERE acknowledged_at IS NULL",
            (_now(),),
        )
        await db.commit()
        return cur.rowcount


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #


def _row_to_dict(row) -> dict[str, Any]:
    d = {k: row[k] for k in row.keys()}
    if d.get("payload_json"):
        try:
            d["payload"] = json.loads(d["payload_json"])
        except json.JSONDecodeError:
            d["payload"] = None
    else:
        d["payload"] = None
    d.pop("payload_json", None)
    return d


async def list_alerts(
    *, since_ts: str | None = None,
    only_unread: bool = False, limit: int = 100,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM dl_alerts WHERE 1=1"
    params: list[Any] = []
    if since_ts:
        sql += " AND ts >= ?"
        params.append(since_ts)
    if only_unread:
        sql += " AND acknowledged_at IS NULL"
    sql += " ORDER BY ts DESC LIMIT ?"
    params.append(limit)

    async with _dbmod.connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(sql, params)
        rows = await cur.fetchall()
    return [_row_to_dict(r) for r in rows]


async def unread_count() -> int:
    async with _dbmod.connect() as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM dl_alerts WHERE acknowledged_at IS NULL"
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 0
