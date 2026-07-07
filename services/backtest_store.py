"""backtest_store.py — persistent cache for strategy backtest runs.

Backtests are heavy (~16 min for 503 symbols), so we run once and store
everything: the per-run summary, every simulated trade with its indicator
snapshots (entry / exit / worst-adverse candle), and the per-symbol scores.
A run is keyed by (strategy, config_hash, universe_hash) — so as long as the
strategy config and the universe are unchanged, we serve the cached run and
never re-replay. Change the strategy → the hash changes → a fresh run.

Lives in its own SQLite file (data/backtest_cache.db) rather than the main /
Turso DB: this is heavy research data, queried offline for review, not part
of the live trading state.

Sync API (sqlite3) — called from the scorer script.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from services.settings_service import DATA_DIR, STRATEGY_CONFIG_DIR

DB_PATH = DATA_DIR / "backtest_cache.db"

_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS backtest_runs (
        run_id TEXT PRIMARY KEY,
        strategy TEXT NOT NULL,
        kind TEXT NOT NULL DEFAULT 'baseline',   -- baseline | candidate
        config_hash TEXT NOT NULL,
        universe_name TEXT,
        universe_hash TEXT NOT NULL,
        is_since TEXT, split TEXT, until TEXT,
        created_at TEXT NOT NULL,
        n_symbols INTEGER, n_trades INTEGER,
        is_pf REAL, is_avg_r REAL, oos_pf REAL, oos_avg_r REAL,
        summary_json TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_bt_runs_key ON "
    "backtest_runs(strategy, config_hash, universe_hash, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS backtest_trades (
        run_id TEXT NOT NULL,
        strategy TEXT NOT NULL,
        symbol TEXT NOT NULL,
        window TEXT,                 -- 'IS' | 'OOS'
        signal_date TEXT, entry_date TEXT, exit_date TEXT,
        direction TEXT,
        entry REAL, stop REAL, tp1 REAL, exit_px REAL, exit_reason TEXT,
        pnl_pct REAL, pnl_r REAL, mfe_r REAL, mae_r REAL, win INTEGER,
        hold_days INTEGER, pqs INTEGER,
        entry_ind_json TEXT, exit_ind_json TEXT, adverse_ind_json TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_bt_trades_run ON backtest_trades(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_bt_trades_sym ON backtest_trades(strategy, symbol)",
    """
    CREATE TABLE IF NOT EXISTS backtest_symbol_scores (
        run_id TEXT NOT NULL,
        strategy TEXT NOT NULL,
        symbol TEXT NOT NULL,
        is_n INTEGER, is_pf REAL, is_wr REAL, is_avg_r REAL, is_total_r REAL,
        oos_n INTEGER, oos_pf REAL, oos_wr REAL, oos_avg_r REAL,
        verdict TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_bt_scores_run ON backtest_symbol_scores(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_bt_scores_sym ON backtest_symbol_scores(strategy, symbol)",
    """
    CREATE TABLE IF NOT EXISTS hypothesis_threads (
        thread_id TEXT PRIMARY KEY,
        strategy TEXT NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        overrides_json TEXT NOT NULL DEFAULT '{}',   -- the param changes to test
        status TEXT NOT NULL DEFAULT 'open',          -- open | adopted | discarded
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        adopted_at TEXT,
        baseline_run_id TEXT,      -- run reflecting the current live config
        candidate_run_id TEXT,     -- run with the overrides applied
        notes TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_threads_strategy ON hypothesis_threads(strategy, created_at DESC)",
]


# ── Hypothesis threads ─────────────────────────────────────────────────────

def create_thread(*, thread_id: str, strategy: str, name: str, description: str,
                  overrides: dict, created_at: str) -> None:
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO hypothesis_threads (thread_id, strategy, name, description, "
            "overrides_json, status, created_at, updated_at) "
            "VALUES (?,?,?,?,?,'open',?,?)",
            (thread_id, strategy, name, description, json.dumps(overrides),
             created_at, created_at),
        )
        conn.commit()
    finally:
        conn.close()


def list_threads(strategy: str | None = None) -> list[dict]:
    conn = _conn()
    try:
        if strategy:
            cur = conn.execute("SELECT * FROM hypothesis_threads WHERE strategy=? "
                               "ORDER BY created_at DESC", (strategy,))
        else:
            cur = conn.execute("SELECT * FROM hypothesis_threads ORDER BY created_at DESC")
        out = []
        for r in cur.fetchall():
            d = dict(r)
            d["overrides"] = json.loads(d.get("overrides_json") or "{}")
            out.append(d)
        return out
    finally:
        conn.close()


def get_thread(thread_id: str) -> dict | None:
    conn = _conn()
    try:
        r = conn.execute("SELECT * FROM hypothesis_threads WHERE thread_id=?",
                         (thread_id,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["overrides"] = json.loads(d.get("overrides_json") or "{}")
        return d
    finally:
        conn.close()


def update_thread(thread_id: str, *, status: str | None = None,
                  baseline_run_id: str | None = None,
                  candidate_run_id: str | None = None,
                  adopted_at: str | None = None, notes: str | None = None,
                  updated_at: str | None = None) -> None:
    sets, params = [], []
    for col, val in (("status", status), ("baseline_run_id", baseline_run_id),
                     ("candidate_run_id", candidate_run_id), ("adopted_at", adopted_at),
                     ("notes", notes), ("updated_at", updated_at)):
        if val is not None:
            sets.append(f"{col}=?"); params.append(val)
    if not sets:
        return
    params.append(thread_id)
    conn = _conn()
    try:
        conn.execute(f"UPDATE hypothesis_threads SET {', '.join(sets)} WHERE thread_id=?", params)
        conn.commit()
    finally:
        conn.close()


def run_summary(run_id: str) -> dict | None:
    """Aggregate metrics for a run, computed from its stored trades — used to
    compare a candidate thread against its baseline."""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT window, pnl_r, win FROM backtest_trades WHERE run_id=?", (run_id,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return None

    def _agg(rs):
        rlist = [r["pnl_r"] for r in rs]
        n = len(rlist)
        if not n:
            return {"n": 0, "wr": 0.0, "pf": 0.0, "avg_r": 0.0, "total_r": 0.0}
        pos = sum(r for r in rlist if r > 0)
        neg = abs(sum(r for r in rlist if r < 0))
        wins = sum(1 for r in rs if r["win"])
        return {"n": n, "wr": wins / n, "pf": (pos / neg if neg > 1e-9 else 99.0),
                "avg_r": sum(rlist) / n, "total_r": sum(rlist)}

    return {"all": _agg(rows),
            "IS": _agg([r for r in rows if r["window"] == "IS"]),
            "OOS": _agg([r for r in rows if r["window"] == "OOS"])}


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    for stmt in _SCHEMA:
        conn.execute(stmt)
    # Additive migration for DBs created before the `kind` column existed.
    try:
        conn.execute("ALTER TABLE backtest_runs ADD COLUMN kind TEXT NOT NULL DEFAULT 'baseline'")
    except sqlite3.OperationalError:
        pass
    return conn


def config_hash(strategy: str) -> str:
    """Hash the strategy's config file — changes when the strategy changes."""
    path = STRATEGY_CONFIG_DIR / f"{strategy}.yaml"
    data = path.read_bytes() if path.exists() else b""
    return hashlib.sha256(data).hexdigest()[:16]


def universe_hash(tickers: list[str]) -> str:
    joined = ",".join(sorted(t.upper() for t in tickers))
    return hashlib.sha256(joined.encode()).hexdigest()[:16]


def find_cached_run(
    strategy: str, cfg_hash: str, uni_hash: str, max_age_days: float | None = None,
    kind: str | None = None,
) -> dict | None:
    """Most recent run matching (strategy, config_hash, universe_hash), or None.
    If max_age_days is set, only returns a run created within that window."""
    conn = _conn()
    try:
        sql = ("SELECT * FROM backtest_runs WHERE strategy=? AND config_hash=? "
               "AND universe_hash=?")
        params = [strategy, cfg_hash, uni_hash]
        if kind:
            sql += " AND kind=?"; params.append(kind)
        sql += " ORDER BY created_at DESC LIMIT 1"
        cur = conn.execute(sql, params)
        row = cur.fetchone()
        if not row:
            return None
        run = dict(row)
        if max_age_days is not None:
            created = datetime.fromisoformat(run["created_at"])
            age = (datetime.now(timezone.utc) - created).total_seconds() / 86400
            if age > max_age_days:
                return None
        return run
    finally:
        conn.close()


def save_run(*, run_id: str, strategy: str, cfg_hash: str, universe_name: str,
             uni_hash: str, is_since: str, split: str, until: str,
             created_at: str, agg: dict, trades: list[dict], scores: list[dict],
             kind: str = "baseline") -> None:
    """Persist a run + all its trades + per-symbol scores in one transaction."""
    conn = _conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO backtest_runs (run_id, strategy, kind, config_hash, "
            "universe_name, universe_hash, is_since, split, until, created_at, "
            "n_symbols, n_trades, is_pf, is_avg_r, oos_pf, oos_avg_r, summary_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, strategy, kind, cfg_hash, universe_name, uni_hash, is_since, split,
             until, created_at, agg.get("n_symbols"), agg.get("n_trades"),
             agg.get("is_pf"), agg.get("is_avg_r"), agg.get("oos_pf"),
             agg.get("oos_avg_r"), json.dumps(agg)),
        )
        conn.executemany(
            "INSERT INTO backtest_trades (run_id, strategy, symbol, window, "
            "signal_date, entry_date, exit_date, direction, entry, stop, tp1, "
            "exit_px, exit_reason, pnl_pct, pnl_r, mfe_r, mae_r, win, hold_days, "
            "pqs, entry_ind_json, exit_ind_json, adverse_ind_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(run_id, strategy, t["symbol"], t["window"], t["signal_date"],
              t["entry_date"], t["exit_date"], t["direction"], t["entry"], t["stop"],
              t["tp1"], t["exit_px"], t["exit_reason"], t["pnl_pct"], t["pnl_r"],
              t["mfe_r"], t["mae_r"], int(t["win"]), t["hold_days"], t["pqs"],
              json.dumps(t["entry_ind"]), json.dumps(t["exit_ind"]),
              json.dumps(t["adverse_ind"])) for t in trades],
        )
        conn.executemany(
            "INSERT INTO backtest_symbol_scores (run_id, strategy, symbol, is_n, "
            "is_pf, is_wr, is_avg_r, is_total_r, oos_n, oos_pf, oos_wr, oos_avg_r, "
            "verdict) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(run_id, strategy, s["symbol"], s["is_n"], s["is_pf"], s["is_wr"],
              s["is_avg_r"], s["is_total_r"], s["oos_n"], s["oos_pf"], s["oos_wr"],
              s["oos_avg_r"], s["verdict"]) for s in scores],
        )
        conn.commit()
    finally:
        conn.close()


def get_scores(run_id: str) -> list[dict]:
    conn = _conn()
    try:
        cur = conn.execute(
            "SELECT * FROM backtest_symbol_scores WHERE run_id=? ORDER BY verdict, symbol",
            (run_id,),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_trades(strategy: str, symbol: str | None = None, run_id: str | None = None,
               limit: int = 1000) -> list[dict]:
    """Trade-by-trade ledger for review, with indicator snapshots decoded."""
    conn = _conn()
    try:
        sql = "SELECT * FROM backtest_trades WHERE strategy=?"
        params: list = [strategy]
        if run_id:
            sql += " AND run_id=?"; params.append(run_id)
        if symbol:
            sql += " AND symbol=?"; params.append(symbol.upper())
        sql += " ORDER BY entry_date LIMIT ?"; params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            for k in ("entry_ind_json", "exit_ind_json", "adverse_ind_json"):
                d[k.replace("_json", "")] = json.loads(d.pop(k) or "{}")
            out.append(d)
        return out
    finally:
        conn.close()


ARCHIVE_DIR = DATA_DIR / "backtest_archive"


def archive_run_to_csv(run_id: str) -> str | None:
    """Export a run's full trade ledger (indicators flattened) to a CSV under
    data/backtest_archive/ before it's superseded/pruned. Returns the path."""
    import csv

    conn = _conn()
    try:
        run = conn.execute("SELECT * FROM backtest_runs WHERE run_id=?", (run_id,)).fetchone()
        if not run:
            return None
        rows = conn.execute(
            "SELECT * FROM backtest_trades WHERE run_id=? ORDER BY symbol, entry_date",
            (run_id,),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return None

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = (run["created_at"] or "")[:10]
    path = ARCHIVE_DIR / f"{run['strategy']}_{stamp}_{run_id[:8]}.csv"

    base = ["symbol", "window", "signal_date", "entry_date", "exit_date", "direction",
            "entry", "stop", "tp1", "exit_px", "exit_reason", "pnl_pct", "pnl_r",
            "mfe_r", "mae_r", "win", "hold_days", "pqs"]
    decoded = []
    ind_cols: list[str] = []
    for r in rows:
        d = dict(r)
        flat = {}
        for pfx in ("entry", "exit", "adverse"):
            for k, v in (json.loads(d.get(f"{pfx}_ind_json") or "{}")).items():
                col = f"{pfx}_{k}"
                flat[col] = v
                if col not in ind_cols:
                    ind_cols.append(col)
        decoded.append((d, flat))
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(base + ind_cols)
        for d, flat in decoded:
            w.writerow([d.get(c) for c in base] + [flat.get(c) for c in ind_cols])
    return str(path)


def prune_old_runs(strategy: str, keep: int = 3, kind: str | None = None,
                   protect: set[str] | None = None) -> int:
    """Keep the newest `keep` runs per (strategy[, kind]); delete older ones and
    their trades/scores. `protect` run_ids are never pruned (e.g. runs a
    hypothesis thread points at). Returns rows deleted from backtest_runs."""
    conn = _conn()
    try:
        sql = "SELECT run_id FROM backtest_runs WHERE strategy=?"
        params = [strategy]
        if kind:
            sql += " AND kind=?"; params.append(kind)
        sql += " ORDER BY created_at DESC"
        cur = conn.execute(sql, params)
        ids = [r[0] for r in cur.fetchall()]
        if protect:
            ids = [i for i in ids if i not in protect]
        stale = ids[keep:]
        if not stale:
            return 0
        qs = ",".join("?" * len(stale))
        conn.execute(f"DELETE FROM backtest_trades WHERE run_id IN ({qs})", stale)
        conn.execute(f"DELETE FROM backtest_symbol_scores WHERE run_id IN ({qs})", stale)
        conn.execute(f"DELETE FROM backtest_runs WHERE run_id IN ({qs})", stale)
        conn.commit()
        return len(stale)
    finally:
        conn.close()
