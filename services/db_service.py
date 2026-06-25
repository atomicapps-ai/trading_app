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
    # Politician copy-trading — trades seen from Capitol Trades
    """
    CREATE TABLE IF NOT EXISTS politician_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ct_trade_id TEXT UNIQUE NOT NULL,
        politician_name TEXT NOT NULL,
        politician_slug TEXT NOT NULL,
        party TEXT,
        chamber TEXT,
        ticker TEXT NOT NULL,
        asset_name TEXT,
        asset_type TEXT,
        transaction_type TEXT NOT NULL,
        transaction_date TEXT,
        published_date TEXT NOT NULL,
        amount_min REAL,
        amount_max REAL,
        copy_status TEXT NOT NULL DEFAULT 'pending',
        copy_plan_id TEXT,
        copy_ts TEXT,
        skip_reason TEXT,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_pt_politician ON politician_trades(politician_slug, published_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_pt_status ON politician_trades(copy_status)",
    # Copy-trading runtime configuration (key-value store)
    """
    CREATE TABLE IF NOT EXISTS copy_trading_config (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    # Per-user dashboard widget settings — three-layer settings model:
    # 1. global registry (code) defines what exists
    # 2. settings.yaml / strategy YAMLs define defaults
    # 3. THIS table stores user overrides
    # Read order: this table → YAML default → code default.
    # `user_id` is "default" for the single-user local case; multi-user
    # later just changes the WHERE clause.
    """
    CREATE TABLE IF NOT EXISTS user_widget_settings (
        user_id       TEXT NOT NULL DEFAULT 'default',
        widget_id     TEXT NOT NULL,
        setting_key   TEXT NOT NULL,
        setting_value TEXT NOT NULL,
        updated_at    TEXT NOT NULL,
        PRIMARY KEY (user_id, widget_id, setting_key)
    )
    """,
    # Senate eFD filings cache — populated by the Senate EFD scraper.
    # Diff against new fetches detects fresh disclosures.
    """
    CREATE TABLE IF NOT EXISTS senate_filings (
        ptr_id TEXT PRIMARY KEY,
        senator_name TEXT NOT NULL,
        senator_slug TEXT NOT NULL,
        senator_first TEXT,
        senator_last TEXT,
        filing_date TEXT NOT NULL,
        pdf_url TEXT NOT NULL,
        raw_label TEXT,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_senate_filings_senator ON senate_filings(senator_slug, filing_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_senate_filings_date ON senate_filings(filing_date DESC)",
    # Senate trades — individual transactions parsed from PTR HTML tables.
    # Key (ptr_id, row_num) is stable across re-parses so we can refresh
    # without duplicating rows.
    """
    CREATE TABLE IF NOT EXISTS senate_trades (
        ptr_id TEXT NOT NULL,
        row_num INTEGER NOT NULL,
        senator_slug TEXT NOT NULL,
        senator_name TEXT NOT NULL,
        transaction_date TEXT NOT NULL,
        owner TEXT,
        ticker TEXT,
        asset_name TEXT,
        asset_type TEXT,
        transaction_type TEXT NOT NULL,
        amount_min REAL,
        amount_max REAL,
        comment TEXT,
        parsed_at TEXT NOT NULL,
        PRIMARY KEY (ptr_id, row_num)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_senate_trades_senator ON senate_trades(senator_slug, transaction_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_senate_trades_ticker ON senate_trades(ticker, transaction_date DESC)",
    # Stock lists — curated/dynamic ticker collections (S&P 500, NASDAQ-100, etc.)
    """
    CREATE TABLE IF NOT EXISTS stock_lists (
        slug TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        source_type TEXT DEFAULT 'static',
        source_url TEXT DEFAULT '',
        tickers_json TEXT NOT NULL DEFAULT '[]',
        ticker_count INTEGER DEFAULT 0,
        last_refreshed_at TEXT,
        created_at TEXT NOT NULL
    )
    """,
    # Performance cache for any politician (followed or not) — populated by
    # /api/copy-trading/compute-all-performance so the add-politician dropdown
    # can surface win rate without recomputing on every page load.
    """
    CREATE TABLE IF NOT EXISTS member_performance_cache (
        slug TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        win_rate_30d REAL,
        avg_return_30d REAL,
        avg_spy_return_30d REAL,
        perf_trade_count INTEGER,
        computed_at TEXT NOT NULL
    )
    """,
    # Followed politicians for copy-trading (one row per politician)
    """
    CREATE TABLE IF NOT EXISTS followed_politicians (
        slug TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        party TEXT DEFAULT '',
        chamber TEXT DEFAULT '',
        score REAL DEFAULT 0,
        trade_count_90d INTEGER DEFAULT 0,
        buy_ratio_pct INTEGER DEFAULT 0,
        last_trade_date TEXT DEFAULT '',
        enabled INTEGER DEFAULT 1,
        added_at TEXT NOT NULL,
        win_rate_30d REAL,
        avg_return_30d REAL,
        avg_spy_return_30d REAL,
        perf_trade_count INTEGER,
        perf_computed_at TEXT
    )
    """,
    # Broker accounts — multi-account credential registry. Replaces the
    # single ALPACA_API_KEY/SECRET pair from .env. Each row is one
    # provider + account_type pair (alpaca paper #1, alpaca paper #2,
    # alpaca live, tradestation sim, tradestation live, …). Exactly one
    # row has is_active=1 at any time; that's the adapter the app uses.
    #
    # Security: credentials are stored plaintext. This matches the
    # existing .env model — single-user local tool, DB file is
    # gitignored, app is bound to localhost/Tailscale.
    """
    CREATE TABLE IF NOT EXISTS broker_accounts (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        slug            TEXT UNIQUE NOT NULL,
        label           TEXT NOT NULL,
        provider        TEXT NOT NULL,        -- 'alpaca' | 'tradestation'
        account_type    TEXT NOT NULL,        -- 'paper' | 'live'
        key_id          TEXT NOT NULL,
        secret          TEXT NOT NULL,
        extra_json      TEXT,                  -- provider-specific bag (TS_REFRESH_TOKEN, TS_ACCOUNT_ID, …)
        is_active       INTEGER NOT NULL DEFAULT 0,
        created_at      TEXT NOT NULL,
        updated_at      TEXT NOT NULL,
        last_connected_at TEXT,
        last_error      TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_broker_accounts_active ON broker_accounts(is_active DESC, id ASC)",
    # Strategy alerts — every detection event the strategy emits.
    # Distinct from pending_approvals (which is the trade plan itself);
    # this is the notification stream surfaced as banners on the
    # dashboard. One row per event, never mutated post-write.
    """
    CREATE TABLE IF NOT EXISTS dl_alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        kind TEXT NOT NULL,             -- lock1_scouted | armed | filled | closed | test
        strategy TEXT NOT NULL,         -- "double_lock"
        symbol TEXT,
        direction TEXT,                 -- long | short | NULL
        plan_id TEXT,                   -- pending_approvals.plan_id when applicable
        title TEXT NOT NULL,            -- short headline shown in the banner
        body TEXT,                      -- expanded detail (multi-line ok)
        payload_json TEXT,              -- arbitrary structured detail
        acknowledged_at TEXT
    )
    """,
    # Indexes for the queries we run often
    "CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_approvals(status, ts_created DESC)",
    "CREATE INDEX IF NOT EXISTS idx_pending_symbol ON pending_approvals(symbol)",
    "CREATE INDEX IF NOT EXISTS idx_pipeline_ts ON pipeline_runs(ts_start DESC)",
    "CREATE INDEX IF NOT EXISTS idx_memory_symbol ON trade_memory(symbol, ts_entered DESC)",
    "CREATE INDEX IF NOT EXISTS idx_widget_settings_lookup ON user_widget_settings(user_id, widget_id)",
    "CREATE INDEX IF NOT EXISTS idx_dl_alerts_ts ON dl_alerts(ts DESC)",
    "CREATE INDEX IF NOT EXISTS idx_dl_alerts_unack ON dl_alerts(acknowledged_at, ts DESC)",
]


# Columns that must exist on pending_approvals — for DBs created by an
# earlier version of this module, we add any missing ones at startup.
_PENDING_EXPECTED_COLUMNS = {
    "ack_json", "execution_json", "broker_order_id",
    "execution_ts", "execution_reject_reason",
}

# universe_presets columns added after initial schema
_UNIVERSE_EXPECTED_COLUMNS = {"title"}

# followed_politicians columns added after initial schema
_FOLLOWED_EXPECTED_COLUMNS = {
    "win_rate_30d": "REAL",
    "avg_return_30d": "REAL",
    "avg_spy_return_30d": "REAL",
    "perf_trade_count": "INTEGER",
    "perf_computed_at": "TEXT",
    "is_favorite": "INTEGER DEFAULT 0",
}


async def _migrate_followed_politicians(db: aiosqlite.Connection) -> None:
    cursor = await db.execute("PRAGMA table_info(followed_politicians)")
    rows = await cursor.fetchall()
    existing = {r[1] for r in rows}
    for col, sqltype in _FOLLOWED_EXPECTED_COLUMNS.items():
        if col in existing:
            continue
        try:
            await db.execute(f"ALTER TABLE followed_politicians ADD COLUMN {col} {sqltype}")
            logger.info("db_service: added column followed_politicians.%s", col)
        except aiosqlite.OperationalError as e:
            if "duplicate column" not in str(e).lower():
                logger.warning("db_service: migrate add %s failed: %s", col, e)


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
        await _migrate_followed_politicians(db)
        await db.commit()
    logger.info("db_service: tables ensured at %s", DB_PATH)
    # Migrate legacy single-politician config into the new table (no-op if already done)
    await migrate_single_politician_config()


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


async def update_plan_json(plan_id: str, plan: dict) -> bool:
    """Overwrite the stored TradePlan for ``plan_id`` with ``plan``.

    Used by the trade-detail edit form to persist mid-trade level changes
    (entry / stop / TP / time-stop deadline). The status column is left
    alone — edits don't change lifecycle stage.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "UPDATE pending_approvals SET plan_json = ? WHERE plan_id = ?",
            (json.dumps(plan), plan_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def expire_stale_plans(timeout_minutes: int = 30) -> int:
    """Mark pending plans older than ``timeout_minutes`` as expired.

    Exception: plans whose entry is good-till-cancelled (``valid_until == "gtc"``)
    are NOT auto-expired — they represent multi-day/swing setups (e.g. Kronos daily)
    whose entry price is valid until cancelled, so a short approval window doesn't
    apply. Session-bound/intraday plans (e.g. double_lock) still expire normally.

    Returns the number of rows expired.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT plan_id, plan_json FROM pending_approvals "
            "WHERE status = 'pending' AND ts_created < ?",
            (cutoff,),
        )
        rows = await cur.fetchall()
        to_expire: list[str] = []
        for r in rows:
            try:
                plan = json.loads(r["plan_json"]) if r["plan_json"] else {}
                valid_until = (plan.get("setup", {}).get("entry", {}) or {}).get("valid_until")
            except Exception:  # noqa: BLE001
                valid_until = None
            if valid_until != "gtc":
                to_expire.append(r["plan_id"])
        for pid in to_expire:
            await db.execute(
                "UPDATE pending_approvals SET status = 'expired' WHERE plan_id = ?", (pid,),
            )
        await db.commit()
        return len(to_expire)


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
    # Single-leg plans (e.g. Kronos, 100% at one target) have no second leg —
    # fall back to TP1 so the detail template's "%.2f"|format(tp2) doesn't crash.
    tp2 = tps[1]["price"] if len(tps) >= 2 else tp1

    # Pivot S/R lines for the chart overlay (from the Kronos pivot context).
    piv = thesis.get("pivots") or {}
    pivot_lines: list[dict] = []
    nr, ns = piv.get("nearest_resistance"), piv.get("nearest_support")
    if nr and nr.get("level"):
        pivot_lines.append({"label": "Resistance", "price": nr["level"], "kind": "resistance"})
    if ns and ns.get("level"):
        pivot_lines.append({"label": "Support", "price": ns["level"], "kind": "support"})
    for src, prefix in ((piv.get("weekly"), "w"), (piv.get("monthly"), "m")):
        if not src:
            continue
        for key, kind in (("R1", "resistance"), ("P", "pivot"), ("S1", "support")):
            if src.get(key) is not None:
                pivot_lines.append({"label": f"{prefix}{key}", "price": src[key], "kind": kind})

    return {
        "plan_id": row["plan_id"],
        "symbol": row["symbol"],
        "name": instrument.get("name") or instrument.get("company_name"),
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
        "pivot_lines": pivot_lines,
        "pivot_confluence": thesis.get("pivot_confluence") or piv.get("confluence"),
        "pivot_note": piv.get("note"),
        # All the factors that made this a prospective trade (for the detail panel).
        "factors": {
            "kronos_prob": thesis.get("kronos_pred_prob"),
            "baseline_prob": thesis.get("baseline_prob"),
            "expected_r": thesis.get("kronos_expected_r"),
            "path_sigma_pct": thesis.get("path_sigma_pct"),
            "horizon_bars": thesis.get("horizon_bars"),
            "nearest_support": piv.get("nearest_support"),
            "nearest_resistance": piv.get("nearest_resistance"),
        },
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


# ---------------------------------------------------------------------- #
# politician_trades
# ---------------------------------------------------------------------- #


async def upsert_politician_trade(
    ct_trade_id: str,
    *,
    politician_name: str,
    politician_slug: str,
    party: str,
    chamber: str,
    ticker: str,
    asset_name: str,
    asset_type: str,
    transaction_type: str,
    transaction_date: str,
    published_date: str,
    amount_min: float,
    amount_max: float,
    copy_status: str = "pending",
) -> bool:
    """Insert a new politician trade; skip if ct_trade_id already exists.

    Returns True if the row was newly inserted, False if it was a duplicate.
    """
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            """
            INSERT OR IGNORE INTO politician_trades
                (ct_trade_id, politician_name, politician_slug, party, chamber,
                 ticker, asset_name, asset_type, transaction_type,
                 transaction_date, published_date, amount_min, amount_max,
                 copy_status, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                ct_trade_id, politician_name, politician_slug, party, chamber,
                ticker, asset_name, asset_type, transaction_type,
                transaction_date, published_date, amount_min, amount_max,
                copy_status, now,
            ),
        )
        await db.commit()
        return cur.rowcount > 0


async def update_politician_trade_copy(
    ct_trade_id: str,
    copy_status: str,
    copy_plan_id: str | None = None,
    skip_reason: str | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE politician_trades
               SET copy_status = ?, copy_plan_id = ?, copy_ts = ?, skip_reason = ?
             WHERE ct_trade_id = ?
            """,
            (copy_status, copy_plan_id, now, skip_reason, ct_trade_id),
        )
        await db.commit()


async def list_politician_trades(
    politician_slug: str | None = None,
    limit: int = 100,
) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if politician_slug:
            cur = await db.execute(
                """SELECT * FROM politician_trades
                   WHERE politician_slug = ?
                   ORDER BY published_date DESC LIMIT ?""",
                (politician_slug, limit),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM politician_trades ORDER BY published_date DESC LIMIT ?",
                (limit,),
            )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_known_trade_ids() -> set[str]:
    """Return all ct_trade_ids we've already seen (for dedup)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT ct_trade_id FROM politician_trades")
        rows = await cur.fetchall()
    return {r[0] for r in rows}


# ---------------------------------------------------------------------- #
# copy_trading_config
# ---------------------------------------------------------------------- #


async def get_copy_config(key: str) -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT value FROM copy_trading_config WHERE key = ?", (key,)
        )
        row = await cur.fetchone()
    return row[0] if row else None


async def set_copy_config(key: str, value: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO copy_trading_config (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, now),
        )
        await db.commit()


async def get_all_copy_config() -> dict[str, str]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT key, value FROM copy_trading_config")
        rows = await cur.fetchall()
    return {r["key"]: r["value"] for r in rows}


# ---------------------------------------------------------------------- #
# followed_politicians
# ---------------------------------------------------------------------- #


async def list_followed_politicians() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            # Favorites pinned to top, then by score desc
            "SELECT * FROM followed_politicians ORDER BY is_favorite DESC, score DESC, name ASC"
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def toggle_followed_politician_favorite(slug: str, is_favorite: bool) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE followed_politicians SET is_favorite = ? WHERE slug = ?",
            (1 if is_favorite else 0, slug),
        )
        await db.commit()


async def add_followed_politician(
    slug: str,
    name: str,
    *,
    party: str = "",
    chamber: str = "",
    score: float = 0.0,
    trade_count_90d: int = 0,
    buy_ratio_pct: int = 0,
    last_trade_date: str = "",
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO followed_politicians
                (slug, name, party, chamber, score, trade_count_90d,
                 buy_ratio_pct, last_trade_date, enabled, added_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(slug) DO UPDATE SET
                name = excluded.name,
                party = excluded.party,
                chamber = excluded.chamber,
                score = excluded.score,
                trade_count_90d = excluded.trade_count_90d,
                buy_ratio_pct = excluded.buy_ratio_pct,
                last_trade_date = excluded.last_trade_date
            """,
            (slug, name, party, chamber, score, trade_count_90d, buy_ratio_pct, last_trade_date, now),
        )
        await db.commit()


async def remove_followed_politician(slug: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM followed_politicians WHERE slug = ?", (slug,))
        await db.commit()


async def toggle_followed_politician(slug: str, enabled: bool) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE followed_politicians SET enabled = ? WHERE slug = ?",
            (1 if enabled else 0, slug),
        )
        await db.commit()


async def update_followed_politician_stats(
    slug: str,
    *,
    score: float | None = None,
    trade_count_90d: int | None = None,
    buy_ratio_pct: int | None = None,
    last_trade_date: str | None = None,
) -> None:
    """Refresh the cached CT stats for a followed politician after a scan."""
    fields, vals = [], []
    if score is not None:
        fields.append("score = ?"); vals.append(score)
    if trade_count_90d is not None:
        fields.append("trade_count_90d = ?"); vals.append(trade_count_90d)
    if buy_ratio_pct is not None:
        fields.append("buy_ratio_pct = ?"); vals.append(buy_ratio_pct)
    if last_trade_date is not None:
        fields.append("last_trade_date = ?"); vals.append(last_trade_date)
    if not fields:
        return
    vals.append(slug)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            f"UPDATE followed_politicians SET {', '.join(fields)} WHERE slug = ?",
            vals,
        )
        await db.commit()


async def get_member_performance_cache_map() -> dict[str, dict]:
    """Return {slug: {win_rate_30d, avg_return_30d, perf_trade_count, computed_at}}
    for all cached members. Used to enrich the add-politician dropdown."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM member_performance_cache")
        rows = await cur.fetchall()
    return {r["slug"]: dict(r) for r in rows}


async def upsert_member_performance(
    slug: str,
    name: str,
    *,
    win_rate_30d: float | None,
    avg_return_30d: float | None,
    avg_spy_return_30d: float | None,
    perf_trade_count: int,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO member_performance_cache
                (slug, name, win_rate_30d, avg_return_30d, avg_spy_return_30d,
                 perf_trade_count, computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                name = excluded.name,
                win_rate_30d = excluded.win_rate_30d,
                avg_return_30d = excluded.avg_return_30d,
                avg_spy_return_30d = excluded.avg_spy_return_30d,
                perf_trade_count = excluded.perf_trade_count,
                computed_at = excluded.computed_at
            """,
            (slug, name, win_rate_30d, avg_return_30d, avg_spy_return_30d,
             perf_trade_count, now),
        )
        await db.commit()


async def update_followed_politician_performance(
    slug: str,
    *,
    win_rate_30d: float | None,
    avg_return_30d: float | None,
    avg_spy_return_30d: float | None,
    perf_trade_count: int,
) -> None:
    """Persist computed performance metrics for a followed politician."""
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE followed_politicians
               SET win_rate_30d = ?, avg_return_30d = ?, avg_spy_return_30d = ?,
                   perf_trade_count = ?, perf_computed_at = ?
             WHERE slug = ?
            """,
            (win_rate_30d, avg_return_30d, avg_spy_return_30d, perf_trade_count, now, slug),
        )
        await db.commit()


# ---------------------------------------------------------------------- #
# senate_filings
# ---------------------------------------------------------------------- #


async def list_senate_filings(senator_slug: str | None = None, limit: int = 1000) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if senator_slug:
            cur = await db.execute(
                """SELECT * FROM senate_filings
                   WHERE senator_slug = ?
                   ORDER BY filing_date DESC LIMIT ?""",
                (senator_slug, limit),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM senate_filings ORDER BY filing_date DESC LIMIT ?",
                (limit,),
            )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def get_known_senate_ptr_ids() -> set[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT ptr_id FROM senate_filings")
        rows = await cur.fetchall()
    return {r[0] for r in rows}


async def upsert_senate_filings(filings: list[dict]) -> dict[str, int]:
    """Bulk-insert filings; tracks new vs updated counts.

    Returns {"new": N, "updated": M}. The caller can use `new` to drive the
    "X new disclosures" UI badge.
    """
    if not filings:
        return {"new": 0, "updated": 0}
    now = datetime.now(timezone.utc).isoformat()
    new = updated = 0
    async with aiosqlite.connect(DB_PATH) as db:
        for f in filings:
            cur = await db.execute(
                """
                INSERT INTO senate_filings
                    (ptr_id, senator_name, senator_slug, senator_first, senator_last,
                     filing_date, pdf_url, raw_label, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ptr_id) DO UPDATE SET
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    f["ptr_id"], f["senator_name"], f["senator_slug"],
                    f.get("senator_first", ""), f.get("senator_last", ""),
                    f["filing_date"], f["pdf_url"], f.get("raw_label", ""),
                    now, now,
                ),
            )
            if cur.rowcount > 0:
                new += 1
            else:
                updated += 1
        await db.commit()
    return {"new": new, "updated": updated}


async def count_senate_filings() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM senate_filings")
        return (await cur.fetchone())[0]


# ---------------------------------------------------------------------- #
# senate_trades — individual transaction rows parsed from PTR HTML tables
# ---------------------------------------------------------------------- #


async def list_senate_trades(
    senator_slug: str | None = None, limit: int = 1000
) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if senator_slug:
            cur = await db.execute(
                """SELECT * FROM senate_trades
                   WHERE senator_slug = ?
                   ORDER BY transaction_date DESC LIMIT ?""",
                (senator_slug, limit),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM senate_trades ORDER BY transaction_date DESC LIMIT ?",
                (limit,),
            )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def upsert_senate_trades(trades: list[dict]) -> int:
    """Bulk upsert. Returns count of rows inserted/updated.

    Each trade dict must include: ptr_id, row_num, senator_slug, senator_name,
    transaction_date, transaction_type. Other fields default to empty.
    """
    if not trades:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        for t in trades:
            await db.execute(
                """
                INSERT INTO senate_trades
                    (ptr_id, row_num, senator_slug, senator_name,
                     transaction_date, owner, ticker, asset_name, asset_type,
                     transaction_type, amount_min, amount_max, comment, parsed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ptr_id, row_num) DO UPDATE SET
                    transaction_date = excluded.transaction_date,
                    owner            = excluded.owner,
                    ticker           = excluded.ticker,
                    asset_name       = excluded.asset_name,
                    asset_type       = excluded.asset_type,
                    transaction_type = excluded.transaction_type,
                    amount_min       = excluded.amount_min,
                    amount_max       = excluded.amount_max,
                    comment          = excluded.comment,
                    parsed_at        = excluded.parsed_at
                """,
                (
                    t["ptr_id"], t["row_num"],
                    t["senator_slug"], t["senator_name"],
                    t["transaction_date"], t.get("owner", ""),
                    t.get("ticker", ""), t.get("asset_name", ""), t.get("asset_type", ""),
                    t["transaction_type"], t.get("amount_min", 0.0), t.get("amount_max", 0.0),
                    t.get("comment", ""), now,
                ),
            )
        await db.commit()
    return len(trades)


async def get_parsed_ptr_ids() -> set[str]:
    """Return set of ptr_ids that already have parsed trades cached."""
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT DISTINCT ptr_id FROM senate_trades")
        rows = await cur.fetchall()
    return {r[0] for r in rows}


async def migrate_single_politician_config() -> None:
    """One-time migration: move the old single followed_politician config key
    into the new followed_politicians table, then remove the old keys."""
    cfg = await get_all_copy_config()
    slug = cfg.get("followed_politician", "").strip()
    name = cfg.get("followed_politician_name", "").strip()
    if not slug:
        return
    # Check whether we've already migrated
    existing = await list_followed_politicians()
    if existing:
        return
    logger.info("db_service: migrating single-politician config (%s) to followed_politicians", slug)
    await add_followed_politician(slug, name or slug)
