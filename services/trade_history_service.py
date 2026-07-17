"""trade_history_service.py — the data layer behind /trades.

Merges the two real stores into one normalized trade list:

  * **closed trades** — the JSONL journal (``trade_logs/*.jsonl``), written by
    ``services.trade_recorder`` on every close. These carry realized P&L / R.
  * **open trades**   — ``pending_approvals`` rows with status ``executed`` /
    ``approved`` / ``open`` (position taken, not yet closed). No realized P&L.

On top of the merged list it computes the page's headline **summary** (overall
performance) and a **strategy ranking** so the operator sees which strategies
are actually earning their keep.
"""
from __future__ import annotations

import logging
from datetime import datetime

from services import db_service, log_service

logger = logging.getLogger(__name__)

_OPEN_STATUSES = {"executed", "approved", "open", "filled", "awaiting_fill"}


def _hold_seconds(ts_a: str, ts_b: str) -> int:
    if not ts_a or not ts_b:
        return 0
    try:
        t1 = datetime.fromisoformat(ts_a.replace("Z", "+00:00"))
        t2 = datetime.fromisoformat(ts_b.replace("Z", "+00:00"))
        return max(0, int((t2 - t1).total_seconds()))
    except ValueError:
        return 0


async def _closed_rows() -> list[dict]:
    """Flatten every closed TradeRecord (JSONL) into a normalized row."""
    try:
        records = await log_service.read_records()
    except Exception as e:  # noqa: BLE001
        logger.warning("trade_history: JSONL read failed (%s)", e)
        return []
    rows: list[dict] = []
    for r in records:
        instr = r.instrument or {}
        lc = r.lifecycle or {}
        setup = r.setup_snapshot or {}
        execn = r.execution or {}
        outc = r.outcome or {}
        ts_entered = lc.get("ts_entered") or lc.get("ts_planned") or ""
        ts_exited = lc.get("ts_exited_last") or lc.get("ts_exited_first") or ""
        rows.append({
            "trade_id": r.trade_id,
            "plan_id": r.plan_id,
            "symbol": instr.get("symbol", ""),
            "direction": setup.get("direction", "long"),
            "strategy": setup.get("strategy_name", "") or "manual",
            "entry": execn.get("avg_entry_price") or execn.get("entry_price_actual"),
            "exit_avg": execn.get("avg_exit_price") or execn.get("exit_price_actual"),
            "pnl_usd": outc.get("pnl_usd", 0.0) or 0.0,
            "pnl_r": outc.get("pnl_r_multiple"),
            "mfe_r": outc.get("mfe_r_multiple"),
            "mae_r": outc.get("mae_r_multiple"),
            "hold_seconds": _hold_seconds(ts_entered, ts_exited),
            "exit_reason": outc.get("exit_reason", ""),
            "mode": r.mode,
            "ts_entered": ts_entered,
            "ts_exited": ts_exited,
            "status": "closed",
            "is_closed": True,
        })
    return rows


async def _open_rows() -> list[dict]:
    """Executed/approved plans that haven't closed yet — the open book."""
    try:
        plans = await db_service.get_pending_plans(status_filter=None, limit=1000)
    except Exception as e:  # noqa: BLE001
        logger.warning("trade_history: pending read failed (%s)", e)
        return []
    rows: list[dict] = []
    for p in plans:
        if (p.get("status") or "").lower() not in _OPEN_STATUSES:
            continue
        rows.append({
            "trade_id": p.get("plan_id"),
            "plan_id": p.get("plan_id"),
            "symbol": p.get("symbol", ""),
            "direction": p.get("direction", "long"),
            "strategy": p.get("strategy", "") or "manual",
            "entry": p.get("entry"),
            "exit_avg": None,
            "pnl_usd": None,
            "pnl_r": None,
            "mfe_r": None,
            "mae_r": None,
            "hold_seconds": 0,
            "exit_reason": "",
            "mode": p.get("mode"),
            "ts_entered": p.get("execution_ts") or p.get("ts_created") or "",
            "ts_exited": "",
            "status": p.get("status", "open"),
            "is_closed": False,
        })
    return rows


async def load_all() -> list[dict]:
    """All trades — closed (realized) + open — newest first."""
    closed = await _closed_rows()
    open_rows = await _open_rows()
    # A plan that has closed shouldn't also show as open.
    closed_plan_ids = {r["plan_id"] for r in closed if r.get("plan_id")}
    open_rows = [r for r in open_rows if r.get("plan_id") not in closed_plan_ids]
    rows = closed + open_rows
    rows.sort(key=lambda x: (x.get("ts_exited") or x.get("ts_entered") or ""),
              reverse=True)
    return rows


# --------------------------------------------------------------------------- #
# Summary + ranking (computed over CLOSED trades only — realized performance)
# --------------------------------------------------------------------------- #


def _perf(closed: list[dict]) -> dict:
    """Core realized-performance metrics over a list of closed rows."""
    n = len(closed)
    if n == 0:
        return dict(n=0, wins=0, losses=0, win_rate=0.0, net_pnl=0.0,
                    gross_profit=0.0, gross_loss=0.0, profit_factor=None,
                    avg_r=None, expectancy_usd=0.0, avg_win=0.0, avg_loss=0.0,
                    best=0.0, worst=0.0)
    pnls = [float(r.get("pnl_usd") or 0.0) for r in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit = sum(wins)
    gross_loss = -sum(losses)
    rs = [float(r["pnl_r"]) for r in closed if r.get("pnl_r") is not None]
    return dict(
        n=n,
        wins=len(wins),
        losses=len(losses),
        win_rate=round(100.0 * len(wins) / n, 1),
        net_pnl=round(sum(pnls), 2),
        gross_profit=round(gross_profit, 2),
        gross_loss=round(gross_loss, 2),
        profit_factor=(round(gross_profit / gross_loss, 2) if gross_loss > 0 else None),
        avg_r=(round(sum(rs) / len(rs), 3) if rs else None),
        expectancy_usd=round(sum(pnls) / n, 2),
        avg_win=round(gross_profit / len(wins), 2) if wins else 0.0,
        avg_loss=round(gross_loss / len(losses), 2) if losses else 0.0,
        best=round(max(pnls), 2),
        worst=round(min(pnls), 2),
    )


def summary(trades: list[dict]) -> dict:
    closed = [t for t in trades if t.get("is_closed")]
    s = _perf(closed)
    s["open_count"] = sum(1 for t in trades if not t.get("is_closed"))
    s["total_count"] = len(trades)
    return s


def _rank_score(p: dict) -> float:
    """Composite quality score for ranking a strategy. Rewards positive
    expectancy (R) and profit factor, scaled by how much we've actually seen
    (a 2-trade fluke shouldn't outrank a 40-trade edge)."""
    n = p["n"]
    pf = p["profit_factor"] if p["profit_factor"] is not None else (
        2.0 if p["gross_loss"] == 0 and p["gross_profit"] > 0 else 0.0)
    avg_r = p["avg_r"] if p["avg_r"] is not None else 0.0
    wr = p["win_rate"] / 100.0
    confidence = min(1.0, n / 20.0)          # full weight at ~20 trades
    raw = (min(pf, 3.0) / 3.0) * 0.45 + max(-1.0, min(avg_r, 2.0)) / 2.0 * 0.35 + wr * 0.20
    return round(raw * confidence, 4)


def rank_strategies(trades: list[dict]) -> list[dict]:
    """Per-strategy realized performance, ranked best→worst."""
    closed = [t for t in trades if t.get("is_closed")]
    by_strat: dict[str, list[dict]] = {}
    for t in closed:
        by_strat.setdefault(t.get("strategy") or "manual", []).append(t)
    out: list[dict] = []
    for strat, rows in by_strat.items():
        p = _perf(rows)
        p["strategy"] = strat
        p["score"] = _rank_score(p)
        p["open_count"] = sum(
            1 for t in trades
            if not t.get("is_closed") and (t.get("strategy") or "manual") == strat
        )
        out.append(p)
    out.sort(key=lambda p: (p["score"], p["net_pnl"]), reverse=True)
    for i, p in enumerate(out, 1):
        p["rank"] = i
    return out
