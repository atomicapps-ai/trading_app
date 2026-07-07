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
            "SELECT * FROM backtest_runs WHERE strategy=? AND kind='baseline' "
            "ORDER BY created_at DESC LIMIT 1", (strategy,),
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


def _eff_hash(strategy: str, overrides: dict | None) -> str:
    """Cache key for a config: the strategy YAML hash, plus the overrides so a
    candidate run doesn't collide with the baseline."""
    import hashlib
    import json
    base = store.config_hash(strategy)
    if not overrides:
        return base
    return hashlib.sha256((base + json.dumps(overrides, sort_keys=True)).encode()
                          ).hexdigest()[:16]


async def run_strategy(
    strategy: str, *, min_trades: int = 15, pf_drop: float = 1.0,
    is_since: str = _DEFAULT_IS_SINCE, split: str = _DEFAULT_SPLIT,
    until: str | None = None, force: bool = True, progress=None,
    overrides: dict | None = None,
) -> dict:
    """Replay, score, archive the superseded run, persist the new one, prune.
    ``overrides`` runs a candidate (live YAML untouched, distinct cache key).
    Returns a summary dict. Heavy (minutes) — call from a background task."""
    from scripts.replay_swing import replay  # heavy import; local

    until = until or date.today().isoformat()
    uni_name, symbols = await _core_symbols()
    if not symbols:
        return {"ok": False, "error": "no core universe"}
    kind = "candidate" if overrides else "baseline"
    cfg_hash = _eff_hash(strategy, overrides)
    uni_hash = store.universe_hash(symbols)

    if not force:
        cached = store.find_cached_run(strategy, cfg_hash, uni_hash, kind=kind)
        if cached:
            scores = store.get_scores(cached["run_id"])
            v = {"KEEP": 0, "DROP": 0, "THIN": 0}
            for s in scores:
                v[s.get("verdict", "THIN")] = v.get(s.get("verdict", "THIN"), 0) + 1
            return {"ok": True, "run_id": cached["run_id"], "cached": True,
                    "n_symbols": cached["n_symbols"], "n_trades": cached["n_trades"],
                    "keep": v["KEEP"], "drop": v["DROP"], "thin": v["THIN"]}

    is_trades = await replay(symbols, is_since, split, strategy,
                             progress=progress, overrides=overrides)
    oos_trades = await replay(symbols, split, until, strategy,
                              progress=progress, overrides=overrides)

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

    # For a baseline re-run, archive the run it supersedes to CSV first.
    archived = None
    if kind == "baseline":
        prev = store.find_cached_run(strategy, cfg_hash, uni_hash, kind="baseline") \
            or _latest_run(strategy)
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
                   trades=trades, scores=scores, kind=kind)
    protect = set()
    for th in store.list_threads(strategy):
        for k in ("baseline_run_id", "candidate_run_id"):
            if th.get(k):
                protect.add(th[k])
    store.prune_old_runs(strategy, keep=5, kind=kind, protect=protect)
    return {"ok": True, "run_id": run_id, "n_symbols": len(rows),
            "n_trades": len(trades), "archived": archived,
            "keep": sum(1 for r in rows if r["verdict"] == "KEEP"),
            "drop": sum(1 for r in rows if r["verdict"] == "DROP"),
            "thin": sum(1 for r in rows if r["verdict"] == "THIN")}


def _delta(base: dict | None, cand: dict | None) -> dict:
    """Candidate-minus-baseline on the headline metrics, with a verdict."""
    if not base or not cand:
        return {}
    b, c = base.get("all", {}), cand.get("all", {})
    d = {k: round((c.get(k, 0) or 0) - (b.get(k, 0) or 0), 3)
         for k in ("n", "wr", "pf", "avg_r", "total_r")}
    # "Better" = higher expectancy (avg_r) AND total_r — the metrics that
    # actually mean more money (PF alone can rise while making less; see the
    # breakeven experiment).
    d["better"] = d["avg_r"] > 0 and d["total_r"] > 0
    return d


async def run_thread(thread_id: str, progress=None) -> dict:
    """Run a hypothesis thread: (re)establish the baseline + run the candidate
    with the thread's overrides, link both runs, return the comparison."""
    th = store.get_thread(thread_id)
    if not th:
        return {"ok": False, "error": "thread not found"}
    strategy = th["strategy"]
    base = await run_strategy(strategy, force=False, progress=progress)      # cache-ok
    cand = await run_strategy(strategy, force=True, progress=progress,
                              overrides=th["overrides"])                     # always fresh
    if not (base.get("ok") and cand.get("ok")):
        return {"ok": False, "error": "run failed", "base": base, "cand": cand}
    from datetime import datetime, timezone
    store.update_thread(thread_id, baseline_run_id=base["run_id"],
                        candidate_run_id=cand["run_id"],
                        updated_at=datetime.now(timezone.utc).isoformat())
    bsum, csum = store.run_summary(base["run_id"]), store.run_summary(cand["run_id"])
    return {"ok": True, "baseline": bsum, "candidate": csum,
            "delta": _delta(bsum, csum),
            "baseline_run_id": base["run_id"], "candidate_run_id": cand["run_id"]}


def _patch_config_yaml(strategy: str, overrides: dict) -> str | None:
    """Deep-merge overrides into strategy_configs/<strategy>.yaml, archiving the
    old file first. Returns the archive path. Changes the config hash → the
    strategy's baseline is now stale and will re-run."""
    import yaml
    from datetime import datetime, timezone
    from services.settings_service import STRATEGY_CONFIG_DIR, PROJECT_ROOT

    path = STRATEGY_CONFIG_DIR / f"{strategy}.yaml"
    if not path.exists():
        return None
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def _merge(dst, src):
        for k, v in src.items():
            if isinstance(v, dict) and isinstance(dst.get(k), dict):
                _merge(dst[k], v)
            else:
                dst[k] = v
    _merge(cfg, overrides)

    archive_dir = PROJECT_ROOT / "strategies" / "config_archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = archive_dir / f"{strategy}_{stamp}.yaml"
    archive.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    return str(archive)


async def adopt_thread(thread_id: str) -> dict:
    """Adopt a candidate as the new live config: patch the strategy YAML
    (old archived), mark the thread adopted. The strategy's baseline then
    shows stale (config changed) until re-run — as intended."""
    from datetime import datetime, timezone
    th = store.get_thread(thread_id)
    if not th:
        return {"ok": False, "error": "thread not found"}
    if not th.get("candidate_run_id"):
        return {"ok": False, "error": "run the thread before adopting"}
    archive = _patch_config_yaml(th["strategy"], th["overrides"])
    now = datetime.now(timezone.utc).isoformat()
    store.update_thread(thread_id, status="adopted", adopted_at=now, updated_at=now)
    return {"ok": True, "archived_config": archive}


async def discard_thread(thread_id: str) -> dict:
    from datetime import datetime, timezone
    store.update_thread(thread_id, status="discarded",
                        updated_at=datetime.now(timezone.utc).isoformat())
    return {"ok": True}


def _latest_run(strategy: str) -> dict | None:
    import sqlite3
    conn = sqlite3.connect(store.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        r = conn.execute("SELECT * FROM backtest_runs WHERE strategy=? AND "
                         "kind='baseline' ORDER BY created_at DESC LIMIT 1",
                         (strategy,)).fetchone()
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
