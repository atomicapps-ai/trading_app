"""trade_recorder.py — capture a closed trade into the ML data pool.

CLAUDE.md non-negotiable: *every completed trade writes a trade_record*. Until
now nothing did — both ``trade_logs/*.jsonl`` and the ``trade_memory`` table
were empty because no close path wrote to them, so ``/trades`` was always blank.

This module is the single writer. On every position close (manual close/TP via
``routers/positions.py`` or the time-stop job in ``agents/executioner.py``) call
``record_close(...)`` — it computes realized P&L / R-multiple, writes a
``TradeRecord`` to the JSONL journal, mirrors a row into ``trade_memory``, and
flips the originating plan to ``closed``.

Best-effort by contract: it never raises into the close path. A close must
succeed at the broker even if journaling hiccups.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from models import TradeRecord
from services import db_service, log_service

logger = logging.getLogger(__name__)


def _pnl(entry: float, exit_price: float, shares: float, direction: str) -> float:
    sign = 1.0 if (direction or "long").lower() == "long" else -1.0
    return (exit_price - entry) * shares * sign


async def record_close(
    *,
    symbol: str,
    direction: str,
    entry_price: float,
    exit_price: float,
    shares: float,
    strategy: str | None = None,
    mode: str = "paper",
    broker: str = "",
    exit_reason: str = "manual",
    plan_id: str | None = None,
    stop_price: float | None = None,
    ts_entered: str | None = None,
    entry_features: dict | None = None,
) -> str | None:
    """Journal a closed trade. Returns the new trade_id, or None on failure.

    ``stop_price`` (if known) yields the R-multiple; without it pnl_r is None.
    """
    try:
        entry = float(entry_price)
        exit_p = float(exit_price)
        qty = abs(float(shares))
        if entry <= 0 or qty <= 0:
            logger.info("record_close: skipping %s — bad entry/shares", symbol)
            return None
    except (TypeError, ValueError):
        logger.info("record_close: skipping %s — non-numeric inputs", symbol)
        return None

    now = datetime.now(timezone.utc).isoformat()
    trade_id = str(uuid4())
    dirn = (direction or "long").lower()

    pnl_usd = _pnl(entry, exit_p, qty, dirn)
    pnl_per_share = _pnl(entry, exit_p, 1.0, dirn)
    r_per_share = abs(entry - float(stop_price)) if stop_price else None
    pnl_r = round(pnl_per_share / r_per_share, 3) if r_per_share else None
    notional = entry * qty
    pnl_pct = round((pnl_usd / notional) * 100, 3) if notional else 0.0
    win = pnl_usd > 0

    record = TradeRecord(
        trade_id=trade_id,
        plan_id=plan_id or trade_id,
        mode=mode if mode in ("research", "paper", "live") else "paper",
        broker=broker or "",
        instrument={"symbol": symbol},
        lifecycle={
            "ts_planned": ts_entered or now,
            "ts_entered": ts_entered or now,
            "ts_exited_first": now,
            "ts_exited_last": now,
        },
        setup_snapshot={
            "strategy_name": strategy or "manual",
            "direction": dirn,
            "stop_price_planned": stop_price,
            "entry_features": entry_features or {},
        },
        execution={
            # Write every field name the readers use (they disagree):
            #   trades._load_real_trades  → avg_entry_price / avg_exit_price
            #   analysis._flatten_record  → entry_price_actual / exit_price_actual
            #   trade_lookup._view_...     → entry_price_actual / exit_price_actual
            "avg_entry_price": round(entry, 4),
            "avg_exit_price": round(exit_p, 4),
            "entry_price_actual": round(entry, 4),
            "entry_price_planned": round(entry, 4),
            "exit_price_actual": round(exit_p, 4),
            "filled_shares": qty,
            "planned_entry_notional": round(notional, 2),
        },
        outcome={
            "pnl_usd": round(pnl_usd, 2),
            "pnl_pct": pnl_pct,
            "pnl_r_multiple": pnl_r,
            "mfe_r_multiple": None,
            "mae_r_multiple": None,
            "win": win,
            "exit_reason": exit_reason,
        },
        postmortem={},
    )

    ok = False
    try:
        await log_service.append_trade_record(record)
        ok = True
    except Exception as exc:  # noqa: BLE001 — journaling must not break the close
        logger.warning("record_close: JSONL append failed for %s: %s", symbol, exc)

    # Mirror into the trade_memory ML pool (best-effort).
    try:
        await db_service.insert_trade_memory({
            "trade_id": trade_id,
            "plan_id": plan_id or trade_id,
            "symbol": symbol,
            "strategy_name": strategy or "manual",
            "direction": dirn,
            "win": int(win),
            "pnl_r_multiple": pnl_r,
            "ts_entered": ts_entered or now,
            "ts_exited": now,
            "mode": mode,
        })
    except Exception as exc:  # noqa: BLE001
        logger.warning("record_close: trade_memory insert failed for %s: %s", symbol, exc)

    # Flip the originating plan to closed so it leaves the open book.
    if plan_id:
        try:
            await db_service.mark_plan_closed(
                plan_id, exit_price=round(exit_p, 4),
                pnl_usd=round(pnl_usd, 2), exit_reason=exit_reason,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("record_close: mark_plan_closed failed for %s: %s", plan_id, exc)

    logger.info("record_close: %s %s %+.2f USD (%s) trade_id=%s",
                symbol, dirn, pnl_usd, exit_reason, trade_id)
    return trade_id if ok else None
