"""setup_backtest_service.py — "how would this scan setup have played out?"

Every setup the scanner produced is archived in ``pending_approvals`` with its
entry / stop / TP levels and the date it fired. This service replays one setup
**forward over historical daily bars** from its scan date and reports the
outcome — did it fill, did it hit the stop / TP1 / TP2, what R-multiple, how
many days, and the best/worst excursion along the way.

Daily-bar convention (only OHLC available intrabar):
  * Entry fills the first day within ``entry_window`` days whose range covers
    the entry price (price actually traded through it). If it never does, the
    setup "never triggered" — no fill.
  * After the fill, each day: if BOTH stop and final target are touched in the
    same bar, we assume the **stop first** (conservative). TP2 is the final
    target (let winners run); TP1 is tracked as a milestone.
  * If neither is hit within ``max_days``, exit at the last close (time stop).

This is a faithful, assumption-explicit daily replay — not a promise of live
fills, but a solid "what would have happened" for reviewing the scanner.
"""
from __future__ import annotations

import logging

import pandas as pd

from services.data_service import DataNotAvailableError, get_bars

logger = logging.getLogger(__name__)

ENTRY_WINDOW_DAYS = 5     # setup must trigger within this many days or it's a no-fill
DEFAULT_MAX_DAYS = 120    # give a swing setup room to resolve


def _f(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


async def backtest_setup(plan: dict, *, max_days: int = DEFAULT_MAX_DAYS) -> dict:
    """Replay one archived setup forward. ``plan`` is a get_pending_plans row
    (keys: symbol, direction, entry, stop, tp1, tp2, ts_created, strategy)."""
    symbol = (plan.get("symbol") or "").upper()
    direction = (plan.get("direction") or "long").lower()
    entry = _f(plan.get("entry"))
    stop = _f(plan.get("stop"))
    tp1 = _f(plan.get("tp1"))
    tp2 = _f(plan.get("tp2")) or tp1
    ts_created = plan.get("ts_created") or ""

    if not symbol or entry is None or stop is None or entry == stop:
        return {"status": "insufficient_setup",
                "note": "setup is missing entry/stop or they're equal"}

    try:
        df = await get_bars(symbol, "1d", min_bars=1)
    except DataNotAvailableError as e:
        return {"status": "no_data", "note": str(e)}
    if df is None or df.empty:
        return {"status": "no_data", "note": f"no daily bars for {symbol}"}

    df = df.rename(columns={c: c.lower() for c in df.columns})
    try:
        start = pd.Timestamp(ts_created)
        if start.tzinfo is None:
            start = start.tz_localize("UTC")
    except Exception:  # noqa: BLE001
        start = df.index[0]
    fwd = df[df.index >= start.normalize()]
    if fwd.empty:
        return {"status": "no_data", "note": "no bars on/after the scan date"}

    long = direction != "short"
    r_per_share = abs(entry - stop)

    # 1) Entry fill — first bar within the window whose range covers entry.
    fill_i = None
    for i in range(min(ENTRY_WINDOW_DAYS, len(fwd))):
        row = fwd.iloc[i]
        if float(row["low"]) <= entry <= float(row["high"]):
            fill_i = i
            break
    if fill_i is None:
        return {
            "status": "no_fill", "symbol": symbol, "direction": direction,
            "entry": entry, "stop": stop, "tp1": tp1, "tp2": tp2,
            "scan_date": str(start.date()),
            "note": f"price never reached the entry within {ENTRY_WINDOW_DAYS} days",
        }

    fill_date = fwd.index[fill_i]
    sim = fwd.iloc[fill_i:]

    # 2) Walk forward to the first stop / TP2, tracking TP1 + excursions.
    tp1_hit = False
    mfe = 0.0   # best favorable excursion, in price
    mae = 0.0   # worst adverse excursion, in price
    exit_price = None
    exit_reason = None
    exit_date = None
    days = 0
    for j in range(min(max_days, len(sim))):
        row = sim.iloc[j]
        hi, lo, cl = float(row["high"]), float(row["low"]), float(row["close"])
        days = j
        # excursions
        if long:
            mfe = max(mfe, hi - entry)
            mae = min(mae, lo - entry)
        else:
            mfe = max(mfe, entry - lo)
            mae = min(mae, entry - hi)

        hit_stop = (lo <= stop) if long else (hi >= stop)
        hit_tp2 = (tp2 is not None) and ((hi >= tp2) if long else (lo <= tp2))
        hit_tp1 = (tp1 is not None) and ((hi >= tp1) if long else (lo <= tp1))

        if hit_tp1:
            tp1_hit = True
        if hit_stop:                       # stop-first on same-bar collision
            exit_price, exit_reason = stop, "stop"
            exit_date = sim.index[j]
            break
        if hit_tp2:
            exit_price, exit_reason = tp2, "tp2"
            exit_date = sim.index[j]
            break
    if exit_price is None:                 # never resolved → time stop at last close
        last = sim.iloc[min(max_days, len(sim)) - 1]
        exit_price = float(last["close"])
        exit_reason = "time"
        exit_date = sim.index[min(max_days, len(sim)) - 1]

    pnl_per_share = (exit_price - entry) if long else (entry - exit_price)
    pnl_r = round(pnl_per_share / r_per_share, 2) if r_per_share else None
    pnl_pct = round((pnl_per_share / entry) * 100, 2) if entry else None
    mfe_r = round(mfe / r_per_share, 2) if r_per_share else None
    mae_r = round(mae / r_per_share, 2) if r_per_share else None

    return {
        "status": "ok",
        "symbol": symbol,
        "direction": direction,
        "strategy": plan.get("strategy"),
        "scan_date": str(start.date()),
        "entry": entry, "stop": stop, "tp1": tp1, "tp2": tp2,
        "filled": True,
        "fill_date": str(fill_date.date()),
        "exit_date": str(exit_date.date()),
        "exit_price": round(exit_price, 2),
        "exit_reason": exit_reason,
        "tp1_hit": tp1_hit,
        "win": pnl_per_share > 0,
        "pnl_r": pnl_r,
        "pnl_pct": pnl_pct,
        "mfe_r": mfe_r,
        "mae_r": mae_r,
        "days_held": int(days),
    }
