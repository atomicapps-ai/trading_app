"""db_service.py — SQLite layer for the app's persistent state.

Three tables, all owned by this module:

    pending_approvals   — active and historical TradePlan proposals +
                          their compliance / risk verdicts. The
                          ``/pending`` page reads from this.
    pipeline_runs       — one row per workflow run. Run history.
    trade_memory        — post-trade learning pool (populated in Phase 7
                          when the executioner writes closed trades).

SQLite path: ``data/claude_trading_app.db`` (gitignored; rebuilds from
``trade_logs/*.jsonl`` on startup per the original Phase 1 design).

All writes are async via aiosqlite. We avoid SQLAlchemy — the schema is
small and the query surface is narrow enough that raw SQL stays readable.

Shape note
----------
``get_pending_plans`` returns dicts shaped for the ``/pending`` Jinja
template (flat keys like ``entry``, ``stop``, ``conviction``) rather
than the full TradePlan JSON. The original TradePlan is always
available via the ``plan_json`` field on each row if a caller needs it.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from services.settings_service import LOCAL_DB_PATH

logger = logging.getLogger(__name__)

DB_PATH: Path = LOCAL_DB_PATH


# ---------------------------------------------------------------------- #
# Schema
# ---------------------------------------------------------------------- #

_SCHEMA = [
    # Pending approval queue
    """
    CREATE TABLE IF NOT EXISTS pending_approvals (
        plan_id TEXT PRIMARY KEY,
        ts_created TEXT NOT NULL,
        symbol TEXT NOT NULL,
        direction TEXT NOT NULL,
        strategy TEXT NOT NULL,
        conviction REAL NOT NULL,
        plan_json TEXT NOT NULL,
        compliance_verdict_json TEXT,
        risk_verdict_json TEXT,
        status TEXT DEFAULT 'pending',
        ack_action TEXT,
        ack_ts TEXT,
        mode TEXT NOT NULL,
        ack_json TEXT,
        execution_json TEXT,
        broker_order_id TEXT,
        execution_ts TEXT,
        execution_reject_reason TEXT
    )
    """,
    # Pipeline run history
    """
    CREATE TABLE IF NOT EXISTS pipeline_runs (
        run_id TEXT PRIMARY KEY,
        workflow_id TEXT,
        ts_start TEXT NOT NULL,
        ts_end TEXT,
        preset_name TEXT,
        mode TEXT,
        symbols_analyzed INTEGER,
        signals_generated INTEGER,
        plans_proposed INTEGER,
        plans_approved INTEGER,
        plans_blocked_json TEXT,
        error_message TEXT,
        status TEXT DEFAULT 'running',
        duration_seconds REAL
    )
    """,
    # Trade memory (populated Phase 7)
    """
    CREATE TABLE IF NOT EXISTS trade_memory (
        trade_id TEXT PRIMARY KEY,
        plan_id TEXT,
        symbol TEXT,
        strategy_name TEXT,
        sector TEXT,
        direction TEXT,
        win INTEGER,
        pnl_r_multiple REAL,
        mfe_r REAL,
        mae_r REAL,
        rsi_14_at_entry REAL,
        atr_pct_at_entry REAL,
        vix_at_entry REAL,
        vix_regime TEXT,
        sma50_distance_pct REAL,
        sma200_distance_pct REAL,
        volume_vs_avg_ratio REAL,
        spy_trend_20d TEXT,
        entry_features_json TEXT,
        learning_tags_json TEXT,
        ts_entered TEXT,
        ts_exited TEXT,
        mode TEXT
    )
    """,
    # Universe presets — Finviz-vocabulary filter configs managed via the UI
    """
    CREATE TABLE IF NOT EXISTS universe_presets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        title TEXT NOT NULL DEFAULT '',
        description TEXT DEFAULT '',
        is_active INTEGER NOT NULL DEFAULT 0,
        filters_json TEXT NOT NULL DEFAULT '{}',
        output_tags_json TEXT NOT NULL DEFAULT '[]',
        notes TEXT DEFAULT '',
        tickers_json TEXT,
        tickers_refreshed_at TEXT,
        tickers_source TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_universe_presets_active ON universe_presets(is_active)",
    # Indexes for the queries we run often
    "CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_approvals(status, ts_created DESC)",
    "CREATE INDEX IF NOT EXISTS idx_pending_symbol ON pending_approvals(symbol)",
    "CREATE INDEX IF NOT EXISTS idx_pipeline_ts ON pipeline_runs(ts_start DESC)",
    "CREATE INDEX IF NOT EXISTS idx_memory_symbol ON trade_memory(symbol, ts_entered DESC)",
]


# Columns that must exist on pending_approvals — for DBs created by an
# earlier version of this module, we add any missing ones at startup.
_PENDING_EXPECTED_COLUMNS = {
    "ack_json", "execution_json", "broker_order_id",
    "execution_ts", "execution_reject_reason",
}

# universe_presets columns added after initial schema
_UNIVERSE_EXPECTED_COLUMNS = {"title"}


async def _migrate_universe_presets(db: aiosqlite.Connection) -> None:
    cursor = await db.execute("PRAGMA table_info(universe_presets)")
    rows = await cursor.fetchall()
    existing = {r[1] for r in rows}
    for col in _UNIVERSE_EXPECTED_COLUMNS - existing:
        try:
            await db.execute(
                f"ALTER TABLE universe_presets ADD COLUMN {col} TEXT NOT NULL DEFAULT ''"
            )
            logger.info("db_service: added column universe_presets.%s", col)
        except aiosqlite.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                logger.warning("db_service: migrate add %s failed: %s", col, e)


async def _migrate_pending_approvals(db: aiosqlite.Connection) -> None:
    """Best-effort additive migration. Doesn't drop anything."""
    cursor = await db.execute("PRAGMA table_info(pending_approvals)")
    rows = await cursor.fetchall()
    existing = {r[1] for r in rows}
    for col in _PENDING_EXPECTED_COLUMNS - existing:
        try:
            await db.execute(f"ALTER TABLE pending_approvals ADD COLUMN {col} TEXT")
            logger.info("db_service: added column pending_approvals.%s", col)
        except aiosqlite.OperationalError as e:
            # Race on concurrent starts — fine, another process added it
            if "duplicate column" not in str(e).lower():
                logger.warning("db_service: migrate add %s failed: %s", col, e)


async def ensure_tables() -> None:
    """Create tables + indexes if they don't exist. Idempotent."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        for stmt in _SCHEMA:
            await db.execute(stmt)
        await _migrate_pending_approvals(db)
        await _migrate_universe_presets(db)
        await db.commit()
    logger.info("db_service: tables ensured at %s", DB_PATH)


# ---------------------------------------------------------------------- #
# universe_presets
# ---------------------------------------------------------------------- #


async def list_universe_presets() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM universe_presets ORDER BY is_active DESC, name ASC"
        )
        rows = await cur.fetchall()
    return [_preset_row_to_dict(r) for r in rows]


async def get_universe_preset(name: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM universe_presets WHERE name = ?", (name,)
        )
        row = await cur.fetchone()
    return _preset_row_to_dict(row) if row else None


async def get_active_universe_preset() -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM universe_presets WHERE is_active = 1 LIMIT 1"
        )
        row = await cur.fetchone()
    return _preset_row_to_dict(row) if row else None


async def create_universe_preset(
    *,
    name: str,
    title: str = "",
    description: str = "",
    filters: dict | None = None,
    output_tags: list[str] | None = None,
    notes: str = "",
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            INSERT INTO universe_presets
                (name, title, description, is_active, filters_json, output_tags_json,
                 notes, created_at, updated_at)
            VALUES (?,?,?,0,?,?,?,?,?)
            """,
            (
                name, title or name, description,
                json.dumps(filters or {}),
                json.dumps(output_tags or []),
                notes, now, now,
            ),
        )
        await db.commit()
        return cur.lastrowid  # type: ignore[return-value]


async def update_universe_preset(
    name: str,
    *,
    title: str | None = None,
    description: str | None = None,
    filters: dict | None = None,
    output_tags: list[str] | None = None,
    notes: str | None = None,
) -> bool:
    existing = await get_universe_preset(name)
    if not existing:
        return False
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            UPDATE universe_presets SET
                title = ?,
                description = ?,
                filters_json = ?,
                output_tags_json = ?,
                notes = ?,
                updated_at = ?
            WHERE name = ?
            """,
            (
                title if title is not None else existing["title"],
                description if description is not None else existing["description"],
                json.dumps(filters) if filters is not None else existing["filters_json_raw"],
                json.dumps(output_tags) if output_tags is not None else existing["output_tags_json_raw"],
                notes if notes is not None else existing["notes"],
                now, name,
            ),
        )
        await db.commit()
        return cur.rowcount > 0


async def delete_universe_preset(name: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM universe_presets WHERE name = ?", (name,)
        )
        await db.commit()
        return cur.rowcount > 0


async def set_active_universe_preset(name: str) -> bool:
    """Make one preset active; clear active flag on all others."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE universe_presets SET is_active = 0")
        cur = await db.execute(
            "UPDATE universe_presets SET is_active = 1 WHERE name = ?", (name,)
        )
        await db.commit()
        return cur.rowcount > 0


async def save_universe_preset_tickers(
    name: str,
    tickers: list[str],
    source: str,
) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            UPDATE universe_presets SET
                tickers_json = ?,
                tickers_refreshed_at = ?,
                tickers_source = ?,
                updated_at = ?
            WHERE name = ?
            """,
            (json.dumps(tickers), now, source, now, name),
        )
        await db.commit()
        return cur.rowcount > 0


async def seed_universe_presets_from_yaml(yaml_presets: list[dict]) -> int:
    """One-time migration: import YAML presets into SQLite if table is empty."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM universe_presets")
        count = (await cur.fetchone())[0]
        if count > 0:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        inserted = 0
        for p in yaml_presets:
            try:
                await db.execute(
                    """
                    INSERT OR IGNORE INTO universe_presets
                        (name, description, is_active, filters_json, output_tags_json,
                         notes, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?)
                    """,
                    (
                        p["name"], p.get("description", ""),
                        1 if inserted == 0 else 0,
                        json.dumps({}),
                        json.dumps(p.get("output_tags", [])),
                        p.get("notes", ""),
                        now, now,
                    ),
                )
                inserted += 1
            except Exception as e:  # noqa: BLE001
                logger.warning("seed_universe_presets: skipped %s: %s", p.get("name"), e)
        await db.commit()
        return inserted


def _preset_row_to_dict(row: Any) -> dict:
    filters_raw = row["filters_json"] or "{}"
    output_tags_raw = row["output_tags_json"] or "[]"
    tickers_raw = row["tickers_json"]
    keys = set(row.keys())
    raw_title = row["title"] if "title" in keys else ""
    name = row["name"]
    return {
        "id": row["id"],
        "name": name,
        "title": raw_title or name,
        "description": row["description"] or "",
        "is_active": bool(row["is_active"]),
        "filters": json.loads(filters_raw),
        "filters_json_raw": filters_raw,
        "output_tags": json.loads(output_tags_raw),
        "output_tags_json_raw": output_tags_raw,
        "notes": row["notes"] or "",
        "tickers": json.loads(tickers_raw) if tickers_raw else [],
        "tickers_refreshed_at": row["tickers_refreshed_at"],
        "tickers_source": row["tickers_source"],
        "ticker_count": len(json.loads(tickers_raw)) if tickers_raw else 0,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# ---------------------------------------------------------------------- #
# pending_approvals
# ---------------------------------------------------------------------- #


async def upsert_pending_plan(
    plan: dict,
    *,
    compliance_verdict: dict | None = None,
    risk_verdict: dict | None = None,
    status: str = "pending",
    strategy: str = "swing_momentum",
) -> None:
    """Write a plan + its verdicts to pending_approvals (insert or replace)."""
    plan_id = plan["plan_id"]
    symbol = plan["instrument"]["symbol"]
    direction = plan["setup"]["direction"]
    conviction = float(plan["thesis"].get("conviction", 0.0))
    ts_created = plan.get("ts_created") or datetime.now(timezone.utc).isoformat()
    mode = plan.get("mode", "paper")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO pending_approvals
                (plan_id, ts_created, symbol, direction, strategy, conviction,
                 plan_json, compliance_verdict_json, risk_verdict_json,
                 status, mode)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(plan_id) DO UPDATE SET
                compliance_verdict_json = excluded.compliance_verdict_json,
                risk_verdict_json = excluded.risk_verdict_json,
                status = excluded.status
            """,
            (
                plan_id, ts_created, symbol, direction, strategy, conviction,
                json.dumps(plan),
                json.dumps(compliance_verdict) if compliance_verdict else None,
                json.dumps(risk_verdict) if risk_verdict else None,
                status,
                mode,
            ),
        )
        await db.commit()


async def get_pending_plans(
    status_filter: str | None = "pending",
    limit: int = 100,
) -> list[dict]:
    """Return plans shaped for the /pending template."""
    sql = "SELECT * FROM pending_approvals"
    params: tuple = ()
    if status_filter:
        sql += " WHERE status = ?"
        params = (status_filter,)
    sql += " ORDER BY ts_created DESC LIMIT ?"
    params = params + (limit,)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(sql, params)
        rows = await cur.fetchall()

    return [_row_to_ui_dict(r) for r in rows]


async def get_plan_by_id(plan_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM pending_approvals WHERE plan_id = ?", (plan_id,),
        )
        row = await cur.fetchone()
    return _row_to_ui_dict(row) if row else None


async def ack_plan(
    plan_id: str,
    action: str,
    ack_record: dict | None = None,
) -> bool:
    """Record a human ack; transition status based on action.

    ``ack_record`` — optional full HumanAckRecord JSON (stored verbatim
    so the executioner and later auditors can verify the exact ack that
    triggered an order placement).
    """
    new_status = {
        "approve": "approved",
        "reject": "rejected",
        "modify": "pending",  # stays in queue; modify lands with a new plan
    }.get(action, "pending")
    ack_ts = (ack_record or {}).get("ts") or datetime.now(timezone.utc).isoformat()
    ack_json = json.dumps(ack_record) if ack_record else None
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            UPDATE pending_approvals
               SET status = ?, ack_action = ?, ack_ts = ?, ack_json = ?
             WHERE plan_id = ?
            """,
            (new_status, action, ack_ts, ack_json, plan_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def record_execution(plan_id: str, execution: dict) -> bool:
    """Persist the ExecutionResult for a plan and set its final status.

    Sets status to 'executed' on placed=True, 'order_rejected' otherwise.
    """
    placed = bool(execution.get("placed"))
    status = "executed" if placed else "order_rejected"
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            UPDATE pending_approvals
               SET execution_json = ?,
                   broker_order_id = ?,
                   execution_ts = ?,
                   execution_reject_reason = ?,
                   status = ?
             WHERE plan_id = ?
            """,
            (
                json.dumps(execution),
                execution.get("broker_order_id"),
                execution.get("ts"),
                execution.get("reject_reason"),
                status,
                plan_id,
            ),
        )
        await db.commit()
        return cur.rowcount > 0


async def expire_stale_plans(timeout_minutes: int = 30) -> int:
    """Mark pending plans older than ``timeout_minutes`` as expired.

    Returns the number of rows updated.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            UPDATE pending_approvals
               SET status = 'expired'
             WHERE status = 'pending' AND ts_created < ?
            """,
            (cutoff,),
        )
        await db.commit()
        return cur.rowcount


async def get_pending_count(status_filter: str | None = "pending") -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        if status_filter:
            cur = await db.execute(
                "SELECT COUNT(*) FROM pending_approvals WHERE status = ?",
                (status_filter,),
            )
        else:
            cur = await db.execute("SELECT COUNT(*) FROM pending_approvals")
        row = await cur.fetchone()
        return int(row[0]) if row else 0


# ---------------------------------------------------------------------- #
# pipeline_runs
# ---------------------------------------------------------------------- #


async def record_pipeline_run(
    *,
    run_id: str,
    workflow_id: str,
    mode: str,
    ts_start: str,
    ts_end: str | None = None,
    preset_name: str | None = None,
    symbols_analyzed: int = 0,
    signals_generated: int = 0,
    plans_proposed: int = 0,
    plans_approved: int = 0,
    plans_blocked: list[dict] | None = None,
    error_message: str | None = None,
    status: str = "complete",
    duration_seconds: float | None = None,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO pipeline_runs
                (run_id, workflow_id, ts_start, ts_end, preset_name, mode,
                 symbols_analyzed, signals_generated, plans_proposed,
                 plans_approved, plans_blocked_json, error_message, status,
                 duration_seconds)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(run_id) DO UPDATE SET
                ts_end = excluded.ts_end,
                symbols_analyzed = excluded.symbols_analyzed,
                signals_generated = excluded.signals_generated,
                plans_proposed = excluded.plans_proposed,
                plans_approved = excluded.plans_approved,
                plans_blocked_json = excluded.plans_blocked_json,
                error_message = excluded.error_message,
                status = excluded.status,
                duration_seconds = excluded.duration_seconds
            """,
            (
                run_id, workflow_id, ts_start, ts_end, preset_name, mode,
                symbols_analyzed, signals_generated, plans_proposed,
                plans_approved,
                json.dumps(plans_blocked) if plans_blocked else None,
                error_message, status, duration_seconds,
            ),
        )
        await db.commit()


async def list_pipeline_runs(limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM pipeline_runs ORDER BY ts_start DESC LIMIT ?",
            (limit,),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------- #
# Row flattening for the pending template
# ---------------------------------------------------------------------- #


def _row_to_ui_dict(row: Any) -> dict:
    """Turn a pending_approvals row into the flat dict the template renders.

    Keeps both worlds: the full TradePlan JSON is preserved under
    ``plan_json`` for callers that need the complete object (e.g. the
    ack handler), and the flat keys match the existing Jinja template.
    """
    plan = json.loads(row["plan_json"]) if row["plan_json"] else {}
    compliance = (
        json.loads(row["compliance_verdict_json"])
        if row["compliance_verdict_json"] else None
    )
    risk_v = (
        json.loads(row["risk_verdict_json"]) if row["risk_verdict_json"] else None
    )
    # New columns may not be present on rows read from older DBs — use
    # dict-style access via keys() so missing columns don't explode.
    keys = set(row.keys())
    execution = (
        json.loads(row["execution_json"])
        if "execution_json" in keys and row["execution_json"] else None
    )
    ack_obj = (
        json.loads(row["ack_json"])
        if "ack_json" in keys and row["ack_json"] else None
    )
    setup = plan.get("setup", {})
    entry = setup.get("entry", {}) or {}
    stop_loss = setup.get("stop_loss", {}) or {}
    initial_stop = stop_loss.get("initial", {}) or {}
    tps = setup.get("take_profit", []) or []
    risk = plan.get("risk", {}) or {}
    thesis = plan.get("thesis", {}) or {}
    instrument = plan.get("instrument", {}) or {}

    tp1 = tps[0]["price"] if len(tps) >= 1 else None
    tp2 = tps[1]["price"] if len(tps) >= 2 else None

    return {
        "plan_id": row["plan_id"],
        "symbol": row["symbol"],
        "direction": row["direction"],
        "strategy": row["strategy"],
        "conviction": row["conviction"],
        "status": row["status"],
        "mode": row["mode"],
        "ts_created": row["ts_created"],
        "ack_action": row["ack_action"],
        "ack_ts": row["ack_ts"],

        # Flat levels the template shows
        "entry": entry.get("price"),
        "stop": initial_stop.get("price"),
        "tp1": tp1,
        "tp2": tp2,
        "risk_usd": risk.get("position_risk_usd"),
        "rr_tp1": risk.get("r_multiple_to_tp1"),
        "rr_tp2": risk.get("r_multiple_to_tp2"),
        "position_size": risk.get("position_size_shares"),
        "notional": risk.get("position_notional_usd"),
        "risk_pct": risk.get("position_risk_pct_of_equity"),

        # Gate-outcome summary (for the decision card + list badges).
        #
        # Semantics:
        #   approved / rejected / resized → the gate actually ran
        #   skipped  → an upstream gate blocked; this one never ran
        #   pending  → the gate is genuinely waiting to run (very rare —
        #              essentially only the brief window between
        #              pipeline_service invoking compliance and risk)
        #
        # When compliance rejects, risk never runs and its verdict is
        # None — displaying "pending" there is misleading, so we show
        # "skipped" instead. The Jinja template styles that neutrally.
        "compliance": compliance["result"] if compliance else "pending",
        "risk_result": (
            risk_v["result"] if risk_v
            else ("skipped" if compliance and compliance.get("result") == "rejected"
                  else "pending")
        ),
        "compliance_verdict": compliance,
        "risk_verdict": risk_v,

        # Context
        "lenses": thesis.get("lenses_contributing") or [],
        "thesis": thesis.get("summary", ""),
        "evidence": plan.get("evidence", []) or [],
        "similar_setups": thesis.get("similar_past_setups") or [],
        "tradingview_chart_url": plan.get("tradingview_chart_url", ""),
        "instrument": instrument,

        # Execution surface
        "execution": execution,
        "broker_order_id": (
            row["broker_order_id"] if "broker_order_id" in keys else None
        ),
        "execution_ts": (
            row["execution_ts"] if "execution_ts" in keys else None
        ),
        "execution_reject_reason": (
            row["execution_reject_reason"] if "execution_reject_reason" in keys else None
        ),
        "ack_record": ack_obj,

        # Full raw plan for callers that need everything
        "plan_json": plan,
    }
