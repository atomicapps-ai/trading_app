"""backtest_runner.py — run + status layer for the backtest UI.

Wraps replay_swing + backtest_store so the /strategies/backtests page can:
  • show, per strategy, the last run's timestamp + summary
  • flag staleness — config changed (must re-run), universe changed, or old
  • trigger a run (archiving the superseded run to CSV first, then replacing
    it in the DB)

The heavy replay itself is scripts/replay_swing; this module owns the
orchestration the router calls.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from services import backtest_store as store
from services import universe_service

# Daily swing strategies that replay_swing can simulate (fvg is separate/intraday).
STRATEGIES = ["momentum_breakout", "macd_run", "coil_breakout", "fear_dip_reversion"]

_DEFAULT_IS_SINCE = "2015-01-01"
_DEFAULT_SPLIT = "2023-01-01"
_STALE_DAYS = 30.0


def _r_multiple(t) -> float | None:
    risk = abs(t.entry - t.stop)
    if risk <= 1e-9:
        return None
    return (t.exit_px - t.entry) / risk if (t.direction or "long") == "long" \
        else (t.entry - t.exit_px) / risk


def _metrics(trades: list) -> dict:
    rs = [r for r in (_r_multiple(t) for t in trades) if r is not None]
    n = len(rs)
    if n == 0:
        return {"n": 0, "win_rate": 0.0, "pf": 0.0, "avg_r": 0.0, "total_r": 0.0}
    wins = [r for r in rs if r > 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(r for r in rs if r < 0))
    pf = (gross_win / gross_loss) if gross_loss > 1e-9 else (99.0 if gross_win > 0 else 0.0)
    return {"n": n, "win_rate": len(wins) / n, "pf": pf,
            "avg_r": sum(rs) / n, "total_r": sum(rs)}


def _classify(is_m: dict, oos_m: dict, min_trades: int, pf_drop: float) -> str:
    if is_m["n"] < min_trades:
        return "THIN"
    is_bad = is_m["pf"] < pf_drop or is_m["avg_r"] <= 0
    oos_bad = oos_m["pf"] < 1.0 or oos_m["avg_r"] <= 0
    return "DROP" if (is_bad and oos_bad) else "KEEP"


async def _core_symbols() -> tuple[str, list[str]]:
    preset = await universe_service.get_core_universe()
    if not preset:
        for name in ("core_universe", "core_universe_100"):
            preset = await universe_service.get_preset_db(name)
            if preset:
                break
    if not preset:
        return "", []
    return preset["name"], [str(s).upper() for s in (preset.get("tickers") or [])]


async def strategy_status(strategy: str) -> dict:
    """Last-run summary + staleness for one strategy. status ∈
    {never_run, config_changed, universe_changed, stale, fresh}."""
    uni_name, symbols = await _core_symbols()
    cur_cfg = store.config_hash(strategy)
    cur_uni = store.universe_hash(symbols) if symbols else ""

    import sqlite3
    conn = sqlite3.connect(store.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        for stmt in store._SCHEMA:
            conn.execute(stmt)
        row = conn.execute(
            "SELECT * FROM backtest_runs WHERE strategy=? ORDER BY created_at DESC LIMIT 1",
            (strategy,),
        ).fetchone()
    finally:
        conn.close()

    out = {"strategy": strategy, "universe": uni_name, "universe_size": len(symbols),
           "cur_config_hash": cur_cfg, "run_id": None, "created_at": None,
           "n_symbols": None, "n_trades": None, "keep": None, "drop": None,
           "thin": None, "status": "never_run", "message": "Never scored — run it."}
    if not row:
        return out

    run = dict(row)
    scores = store.get_scores(run["run_id"])
    verdicts = {"KEEP": 0, "DROP": 0, "THIN": 0}
    for s in scores:
        verdicts[s.get("verdict", "THIN")] = verdicts.get(s.get("verdict", "THIN"), 0) + 1
    out.update({"run_id": run["run_id"], "created_at": run["created_at"],
                "n_symbols": run["n_symbols"], "n_trades": run["n_trades"],
                "keep": verdicts["KEEP"], "drop": verdicts["DROP"], "thin": verdicts["THIN"]})

    age_days = (datetime.now(timezone.utc)
                - datetime.fromisoformat(run["created_at"])).total_seconds() / 86400
    if run["config_hash"] != cur_cfg:
        out["status"] = "config_changed"
        out["message"] = "Strategy changed since this run — results are INVALID. Re-run."
    elif cur_uni and run["universe_hash"] != cur_uni:
        out["status"] = "universe_changed"
        out["message"] = "Universe changed since this run — re-run to refresh."
    elif age_days > _STALE_DAYS:
        out["status"] = "stale"
        out["message"] = f"Last run {age_days:.0f} days ago — consider re-running."
    else:
        out["status"] = "fresh"
        out["message"] = f"Current ({age_days:.1f} days old)."
    return out


async def all_statuses() -> list[dict]:
    return [await strategy_status(s) for s in STRATEGIES]


async def run_strategy(
    strategy: str, *, min_trades: int = 15, pf_drop: float = 1.0,
    is_since: str = _DEFAULT_IS_SINCE, split: str = _DEFAULT_SPLIT,
    until: str | None = None, force: bool = True, progress=None,
) -> dict:
    """Replay, score, archive the superseded run, persist the new one, prune.
    Returns a summary dict. Heavy (minutes) — call from a background task."""
    from scripts.replay_swing import replay  # heavy import; local

    until = until or date.today().isoformat()
    uni_name, symbols = await _core_symbols()
    if not symbols:
        return {"ok": False, "error": "no core universe"}
    cfg_hash = store.config_hash(strategy)
    uni_hash = store.universe_hash(symbols)

    is_trades = await replay(symbols, is_since, split, strategy, progress=progress)
    oos_trades = await replay(symbols, split, until, strategy, progress=progress)

    by_is: dict[str, list] = {}
    by_oos: dict[str, list] = {}
    for t in is_trades:
        by_is.setdefault(t.symbol, []).append(t)
    for t in oos_trades:
        by_oos.setdefault(t.symbol, []).append(t)

    rows = []
    for sym in symbols:
        im, om = _metrics(by_is.get(sym, [])), _metrics(by_oos.get(sym, []))
        if im["n"] == 0 and om["n"] == 0:
            continue
        rows.append({"sym": sym, "is": im, "oos": om,
                     "verdict": _classify(im, om, min_trades, pf_drop)})

    # Archive the run this one supersedes (if any), then persist + prune.
    prev = store.find_cached_run(strategy, cfg_hash, uni_hash) or _latest_run(strategy)
    archived = store.archive_run_to_csv(prev["run_id"]) if prev else None

    run_id = str(uuid.uuid4())
    trades = [_td(t, "IS") for t in is_trades] + [_td(t, "OOS") for t in oos_trades]
    scores = [{"symbol": r["sym"], "is_n": r["is"]["n"], "is_pf": r["is"]["pf"],
               "is_wr": r["is"]["win_rate"], "is_avg_r": r["is"]["avg_r"],
               "is_total_r": r["is"]["total_r"], "oos_n": r["oos"]["n"],
               "oos_pf": r["oos"]["pf"], "oos_wr": r["oos"]["win_rate"],
               "oos_avg_r": r["oos"]["avg_r"], "verdict": r["verdict"]} for r in rows]
    store.save_run(run_id=run_id, strategy=strategy, cfg_hash=cfg_hash,
                   universe_name=uni_name, uni_hash=uni_hash, is_since=is_since,
                   split=split, until=until,
                   created_at=datetime.now(timezone.utc).isoformat(),
                   agg={"n_symbols": len(rows), "n_trades": len(trades)},
                   trades=trades, scores=scores)
    store.prune_old_runs(strategy, keep=5)
    return {"ok": True, "run_id": run_id, "n_symbols": len(rows),
            "n_trades": len(trades), "archived": archived,
            "keep": sum(1 for r in rows if r["verdict"] == "KEEP"),
            "drop": sum(1 for r in rows if r["verdict"] == "DROP"),
            "thin": sum(1 for r in rows if r["verdict"] == "THIN")}


def _latest_run(strategy: str) -> dict | None:
    import sqlite3
    conn = sqlite3.connect(store.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        r = conn.execute("SELECT * FROM backtest_runs WHERE strategy=? "
                         "ORDER BY created_at DESC LIMIT 1", (strategy,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def _td(t, window: str) -> dict:
    return {"symbol": t.symbol, "window": window, "signal_date": t.date_str,
            "entry_date": t.entry_date, "exit_date": t.exit_date,
            "direction": t.direction, "entry": t.entry, "stop": t.stop, "tp1": t.tp,
            "exit_px": t.exit_px, "exit_reason": t.exit_reason, "pnl_pct": t.pnl_pct,
            "pnl_r": t.pnl_r, "mfe_r": t.mfe_r, "mae_r": t.mae_r, "win": t.win,
            "hold_days": t.hold_days, "pqs": t.pqs, "entry_ind": t.entry_ind,
            "exit_ind": t.exit_ind, "adverse_ind": t.adverse_ind}
