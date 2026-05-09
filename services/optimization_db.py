"""optimization_db.py — SQLite layer for the per-symbol parameter optimizer.

Schema captures three things at every level:
  1. The numbers (WR, PF, drawdown, score)
  2. The reasoning (why each param value was chosen, why a winner was picked)
  3. The full provenance (when, on what bars, with what code)

Why it's its own DB and not the main claude_trading_app.db: the optimizer
writes thousands of rows per run, and we want it to be append-only / never
mutated by app code. Keeping it isolated also means we can wipe and rerun
without disturbing live trade state.

Path: data/optimization_results.db
"""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from services.settings_service import DATA_DIR

log = logging.getLogger(__name__)

DB_PATH: Path = DATA_DIR / "optimization_results.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS optimization_runs (
  run_id            TEXT PRIMARY KEY,
  strategy_slug     TEXT NOT NULL,
  symbol            TEXT NOT NULL,
  bars_interval     TEXT NOT NULL,
  params_json       TEXT NOT NULL,
  n_trades          INTEGER NOT NULL,
  wins              INTEGER NOT NULL,
  losses            INTEGER NOT NULL,
  wr_pct            REAL NOT NULL,
  profit_factor     REAL NOT NULL,
  net_pnl_usd       REAL NOT NULL,
  gross_profit_usd  REAL NOT NULL,
  gross_loss_usd    REAL NOT NULL,
  avg_r_multiple    REAL NOT NULL,
  max_drawdown_pct  REAL NOT NULL,
  score             REAL NOT NULL,
  window_start      TEXT NOT NULL,
  window_end        TEXT NOT NULL,
  ran_at            TEXT NOT NULL,
  duration_seconds  REAL NOT NULL,
  notes             TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_strategy_symbol
  ON optimization_runs(strategy_slug, symbol);
CREATE INDEX IF NOT EXISTS idx_runs_score
  ON optimization_runs(strategy_slug, symbol, score DESC);

CREATE TABLE IF NOT EXISTS param_reasoning (
  run_id        TEXT NOT NULL,
  param_name    TEXT NOT NULL,
  param_value   TEXT NOT NULL,
  reasoning     TEXT NOT NULL,
  source        TEXT NOT NULL,        -- 'optimizer'|'author_default'|'manual_override'
  PRIMARY KEY (run_id, param_name),
  FOREIGN KEY (run_id) REFERENCES optimization_runs(run_id)
);

CREATE TABLE IF NOT EXISTS best_per_symbol (
  strategy_slug         TEXT NOT NULL,
  symbol                TEXT NOT NULL,
  run_id                TEXT NOT NULL,
  selected_at           TEXT NOT NULL,
  selection_rationale   TEXT NOT NULL,
  PRIMARY KEY (strategy_slug, symbol),
  FOREIGN KEY (run_id) REFERENCES optimization_runs(run_id)
);

CREATE TABLE IF NOT EXISTS optimizer_checkpoints (
  strategy_slug   TEXT NOT NULL,
  symbol          TEXT NOT NULL,
  combos_done     TEXT NOT NULL,   -- json array of param-hash strings
  combos_planned  INTEGER NOT NULL,
  last_updated    TEXT NOT NULL,
  PRIMARY KEY (strategy_slug, symbol)
);

CREATE TABLE IF NOT EXISTS analysis_log (
  ts            TEXT NOT NULL,
  level         TEXT NOT NULL,       -- 'info'|'warn'|'finding'
  scope         TEXT NOT NULL,       -- 'global' | 'strategy:slug' | 'pair:slug:SYM'
  message       TEXT NOT NULL
);

-- Random-search engine table (Phase F).
-- Each row is one trial: a meta-strategy config + its score on one symbol +
-- feature columns describing the symbol/regime context for later analysis.
-- Designed to grow to millions of rows; index by score for top-K queries.
CREATE TABLE IF NOT EXISTS random_search_trials (
  trial_id              TEXT PRIMARY KEY,
  symbol                TEXT NOT NULL,
  bars_interval         TEXT NOT NULL,
  -- meta-strategy config (categorical + continuous params, full json blob)
  meta_config_json      TEXT NOT NULL,
  -- broken out for query speed
  entry_primitive       TEXT NOT NULL,
  stop_type             TEXT NOT NULL,
  tp_type               TEXT NOT NULL,
  regime_filter_count   INTEGER NOT NULL,
  uses_volume_filter    INTEGER NOT NULL,    -- 0/1
  -- outcome
  n_trades              INTEGER NOT NULL,
  wr_pct                REAL NOT NULL,
  profit_factor         REAL NOT NULL,
  net_pnl_usd           REAL NOT NULL,
  avg_r_multiple        REAL NOT NULL,
  max_drawdown_pct      REAL NOT NULL,
  score                 REAL NOT NULL,
  -- in-sample / out-of-sample split (computed at write time)
  is_score              REAL,                 -- 2022-2024 score
  oos_score             REAL,                 -- 2025-2026 score
  is_oos_gap_pct        REAL,                 -- (is_score - oos_score)/is_score
  -- feature vector (json: symbol_class, vol pct, trend regime pct, etc.)
  feature_vector_json   TEXT,
  -- provenance
  ran_at                TEXT NOT NULL,
  duration_ms           INTEGER NOT NULL,
  window_start          TEXT NOT NULL,
  window_end            TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rst_score
  ON random_search_trials(score DESC);
CREATE INDEX IF NOT EXISTS idx_rst_symbol_score
  ON random_search_trials(symbol, score DESC);
CREATE INDEX IF NOT EXISTS idx_rst_oos
  ON random_search_trials(oos_score DESC) WHERE oos_score IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_rst_entry
  ON random_search_trials(entry_primitive, score DESC);
"""


@dataclass
class RunRecord:
    run_id: str
    strategy_slug: str
    symbol: str
    bars_interval: str
    params_json: str
    n_trades: int
    wins: int
    losses: int
    wr_pct: float
    profit_factor: float
    net_pnl_usd: float
    gross_profit_usd: float
    gross_loss_usd: float
    avg_r_multiple: float
    max_drawdown_pct: float
    score: float
    window_start: str
    window_end: str
    ran_at: str
    duration_seconds: float
    notes: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA journal_mode=WAL")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def ensure_schema() -> None:
    with _conn() as c:
        c.executescript(_SCHEMA)


def insert_run(
    record: RunRecord,
    param_reasoning_rows: list[dict],
) -> None:
    """Atomically insert one optimizer run and all per-param reasoning rows.

    `param_reasoning_rows`: list of dicts with keys
        param_name, param_value, reasoning, source
    """
    with _conn() as c:
        c.execute("""
            INSERT INTO optimization_runs (
              run_id, strategy_slug, symbol, bars_interval, params_json,
              n_trades, wins, losses, wr_pct, profit_factor, net_pnl_usd,
              gross_profit_usd, gross_loss_usd, avg_r_multiple,
              max_drawdown_pct, score, window_start, window_end,
              ran_at, duration_seconds, notes
            ) VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
        """, (
            record.run_id, record.strategy_slug, record.symbol,
            record.bars_interval, record.params_json,
            record.n_trades, record.wins, record.losses,
            record.wr_pct, record.profit_factor, record.net_pnl_usd,
            record.gross_profit_usd, record.gross_loss_usd,
            record.avg_r_multiple, record.max_drawdown_pct, record.score,
            record.window_start, record.window_end, record.ran_at,
            record.duration_seconds, record.notes,
        ))
        for row in param_reasoning_rows:
            c.execute("""
                INSERT INTO param_reasoning (
                  run_id, param_name, param_value, reasoning, source
                ) VALUES (?, ?, ?, ?, ?)
            """, (
                record.run_id, row["param_name"],
                str(row["param_value"]), row["reasoning"], row["source"],
            ))


def upsert_best_per_symbol(
    strategy_slug: str,
    symbol: str,
    run_id: str,
    rationale: str,
) -> None:
    with _conn() as c:
        c.execute("""
            INSERT OR REPLACE INTO best_per_symbol (
              strategy_slug, symbol, run_id, selected_at, selection_rationale
            ) VALUES (?, ?, ?, ?, ?)
        """, (strategy_slug, symbol, run_id, _now_iso(), rationale))


def get_done_combos(strategy_slug: str, symbol: str) -> set[str]:
    with _conn() as c:
        row = c.execute("""
            SELECT combos_done FROM optimizer_checkpoints
            WHERE strategy_slug = ? AND symbol = ?
        """, (strategy_slug, symbol)).fetchone()
        if row is None:
            return set()
        return set(json.loads(row[0]))


def upsert_checkpoint(
    strategy_slug: str,
    symbol: str,
    combos_done: Iterable[str],
    combos_planned: int,
) -> None:
    arr = sorted(set(combos_done))
    with _conn() as c:
        c.execute("""
            INSERT OR REPLACE INTO optimizer_checkpoints (
              strategy_slug, symbol, combos_done, combos_planned, last_updated
            ) VALUES (?, ?, ?, ?, ?)
        """, (strategy_slug, symbol, json.dumps(arr), combos_planned, _now_iso()))


def log_analysis(level: str, scope: str, message: str) -> None:
    with _conn() as c:
        c.execute("""
            INSERT INTO analysis_log (ts, level, scope, message)
            VALUES (?, ?, ?, ?)
        """, (_now_iso(), level, scope, message))


def fetch_top_n(strategy_slug: str, symbol: str, n: int = 5) -> list[dict]:
    with _conn() as c:
        c.row_factory = sqlite3.Row
        rows = c.execute("""
            SELECT * FROM optimization_runs
            WHERE strategy_slug = ? AND symbol = ?
            ORDER BY score DESC
            LIMIT ?
        """, (strategy_slug, symbol, n)).fetchall()
        return [dict(r) for r in rows]


def insert_random_trial(trial: dict) -> None:
    """Insert one row into random_search_trials. Caller computes feature_vector
    + scores; we just persist the dict."""
    cols = [
        "trial_id", "symbol", "bars_interval", "meta_config_json",
        "entry_primitive", "stop_type", "tp_type",
        "regime_filter_count", "uses_volume_filter",
        "n_trades", "wr_pct", "profit_factor", "net_pnl_usd",
        "avg_r_multiple", "max_drawdown_pct", "score",
        "is_score", "oos_score", "is_oos_gap_pct",
        "feature_vector_json", "ran_at", "duration_ms",
        "window_start", "window_end",
    ]
    values = [trial.get(c) for c in cols]
    placeholders = ",".join("?" * len(cols))
    with _conn() as c:
        c.execute(
            f"INSERT INTO random_search_trials ({','.join(cols)}) VALUES ({placeholders})",
            values,
        )


def insert_random_trials_batch(trials: list[dict]) -> None:
    """Bulk insert. Used by the random search to commit a batch atomically
    every N trials (saves on transaction overhead)."""
    if not trials:
        return
    cols = [
        "trial_id", "symbol", "bars_interval", "meta_config_json",
        "entry_primitive", "stop_type", "tp_type",
        "regime_filter_count", "uses_volume_filter",
        "n_trades", "wr_pct", "profit_factor", "net_pnl_usd",
        "avg_r_multiple", "max_drawdown_pct", "score",
        "is_score", "oos_score", "is_oos_gap_pct",
        "feature_vector_json", "ran_at", "duration_ms",
        "window_start", "window_end",
    ]
    placeholders = ",".join("?" * len(cols))
    rows = [tuple(t.get(c) for c in cols) for t in trials]
    with _conn() as c:
        c.executemany(
            f"INSERT INTO random_search_trials ({','.join(cols)}) VALUES ({placeholders})",
            rows,
        )


def random_trial_count(symbol: str | None = None) -> int:
    with _conn() as c:
        if symbol:
            r = c.execute(
                "SELECT COUNT(*) FROM random_search_trials WHERE symbol=?",
                (symbol,),
            ).fetchone()
        else:
            r = c.execute("SELECT COUNT(*) FROM random_search_trials").fetchone()
        return int(r[0])


def fetch_best_per_symbol_table() -> list[dict]:
    """One row per (strategy, symbol) with the winning params, score, and rationale."""
    with _conn() as c:
        c.row_factory = sqlite3.Row
        rows = c.execute("""
            SELECT b.strategy_slug, b.symbol, b.selection_rationale,
                   r.params_json, r.n_trades, r.wr_pct, r.profit_factor,
                   r.net_pnl_usd, r.score, r.bars_interval,
                   r.window_start, r.window_end
            FROM best_per_symbol b
            JOIN optimization_runs r ON r.run_id = b.run_id
            ORDER BY b.strategy_slug, b.symbol
        """).fetchall()
        return [dict(r) for r in rows]
