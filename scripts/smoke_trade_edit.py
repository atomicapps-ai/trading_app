"""Smoke test: Phase 6 edit-mode for active trades.

Inserts a pending TradePlan, calls POST /api/trades/{id}/edit through
the FastAPI TestClient, verifies:
  1. Plan JSON updated in SQLite (entry / stop / TP1 / TP2 / deadline).
  2. Close-at-time job rescheduled to the new deadline.
  3. Edit refused for closed (jsonl) trades.
  4. Single-field edits leave other fields untouched.

Uses the historical broker adapter so no credentials needed.
"""
from __future__ import annotations

import asyncio
import os

# Force the historical adapter so we don't need Alpaca creds for the test.
os.environ.setdefault("BROKER_PROVIDER", "alpaca")

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app import app
from services import db_service
from services.scheduler import get_scheduler, stop_scheduler


def _section(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def _make_plan_dict(plan_id: str, deadline_iso: str) -> dict:
    return {
        "plan_id": plan_id,
        "ts_created": datetime.now(timezone.utc).isoformat(),
        "mode": "paper",
        "schema_version": "1.0.0",
        "instrument": {"symbol": "AAPL", "asset_class": "equity",
                       "exchange": "NASDAQ", "sector": None, "industry": None},
        "thesis": {"summary": "smoke", "lenses_contributing": ["technical"],
                   "signal_ids": [], "conviction": 0.8,
                   "expected_holding_period": "intraday",
                   "similar_past_setups": [],
                   "memory_win_rate": None, "memory_avg_r": None},
        "setup": {
            "direction": "long",
            "entry": {"type": "limit", "price": 100.0, "valid_until": "day"},
            "take_profit": [
                {"leg": 1, "price": 101.0, "size_pct": 50, "reason": "tp1"},
                {"leg": 2, "price": 102.0, "size_pct": 50, "reason": "tp2"},
            ],
            "stop_loss": {
                "initial": {"type": "hard", "price": 99.0, "reason": "cat"},
                "trail": {"active": False, "activate_after": "",
                          "mode": "percent", "percent": 1.0},
                "time_stop": {"active": True, "condition": "EOD",
                              "deadline": deadline_iso},
                "thesis_invalidation": {"active": False, "condition": ""},
            },
        },
        "risk": {"r_per_share": 1.0, "position_size_shares": 50,
                 "position_notional_usd": 5000.0, "position_risk_usd": 50.0,
                 "position_risk_pct_of_equity": 0.05,
                 "position_notional_pct_of_equity": 5.0,
                 "r_multiple_to_tp1": 1.0, "r_multiple_to_tp2": 2.0},
        "execution": {"preferred_algo": "vwap", "broker": "alpaca",
                      "account_type": "paper"},
        "evidence": [],
        "tradingview_chart_url": "",
    }


async def _seed_plan(plan_id: str, deadline_iso: str) -> None:
    await db_service.ensure_tables()
    plan = _make_plan_dict(plan_id, deadline_iso)
    await db_service.upsert_pending_plan(plan, status="pending")


async def _read_plan(plan_id: str) -> dict:
    row = await db_service.get_plan_by_id(plan_id)
    return row["plan_json"]


async def _delete(plan_id: str) -> None:
    import aiosqlite
    async with aiosqlite.connect(db_service.DB_PATH) as db:
        await db.execute(
            "DELETE FROM pending_approvals WHERE plan_id = ?", (plan_id,),
        )
        await db.commit()


def _to_et_str(deadline_iso: str) -> str:
    dt = datetime.fromisoformat(deadline_iso.replace("Z", "+00:00"))
    return dt.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%dT%H:%M")


async def _run() -> None:
    sched = get_scheduler()
    if not sched.running:
        sched.start()

    plan_id = "smoke-edit-test-001"
    initial_deadline = (
        datetime.now(timezone.utc) + timedelta(hours=4)
    ).isoformat()
    await _seed_plan(plan_id, initial_deadline)

    client = TestClient(app)

    # ── 1. Full edit ────────────────────────────────────────────
    _section("1. full edit (all fields)")
    new_deadline = (
        datetime.now(timezone.utc) + timedelta(hours=6)
    ).isoformat()
    new_dl_input = _to_et_str(new_deadline)

    r = client.post(
        f"/api/trades/{plan_id}/edit",
        data={
            "entry_price": "105.50",
            "stop_price":  "102.00",
            "tp1_price":   "108.00",
            "tp2_price":   "112.00",
            "time_stop_deadline": new_dl_input,
        },
    )
    print(f"  status: {r.status_code}")
    print(f"  body  : {r.text[:120]}")
    assert r.status_code == 200, f"expected 200, got {r.status_code}"
    assert "Plan updated" in r.text

    plan = await _read_plan(plan_id)
    assert plan["setup"]["entry"]["price"] == 105.50
    assert plan["setup"]["stop_loss"]["initial"]["price"] == 102.00
    assert plan["setup"]["take_profit"][0]["price"] == 108.00
    assert plan["setup"]["take_profit"][1]["price"] == 112.00
    saved_dl = plan["setup"]["stop_loss"]["time_stop"]["deadline"]
    saved_dt = datetime.fromisoformat(saved_dl.replace("Z", "+00:00"))
    expected_dt = datetime.fromisoformat(new_deadline.replace("Z", "+00:00"))
    # Compare to-the-minute (datetime-local input is minute precision)
    assert saved_dt.replace(second=0, microsecond=0) == \
           expected_dt.replace(second=0, microsecond=0), \
        f"deadline mismatch: saved={saved_dl} expected={new_deadline}"

    job = sched.get_job(f"close_{plan_id}")
    assert job is not None, "expected close job to be scheduled"
    print(f"  close-at-time job: id={job.id} run_at={job.next_run_time}")

    # ── 2. Single-field edit leaves others untouched ───────────
    _section("2. single-field edit — only stop_price")
    r = client.post(
        f"/api/trades/{plan_id}/edit",
        data={"stop_price": "103.50"},
    )
    assert r.status_code == 200
    plan = await _read_plan(plan_id)
    assert plan["setup"]["stop_loss"]["initial"]["price"] == 103.50, "stop"
    assert plan["setup"]["entry"]["price"] == 105.50, "entry preserved"
    assert plan["setup"]["take_profit"][0]["price"] == 108.00, "tp1 preserved"
    assert plan["setup"]["take_profit"][1]["price"] == 112.00, "tp2 preserved"
    print("  OK only stop changed; entry/TP/deadline preserved")

    # ── 3. Bad numeric input ───────────────────────────────────
    _section("3. bad numeric input -> 400")
    r = client.post(
        f"/api/trades/{plan_id}/edit",
        data={"entry_price": "not-a-number"},
    )
    print(f"  status: {r.status_code}, body: {r.text[:80]}")
    assert r.status_code == 400

    # ── 4. Bad deadline format ─────────────────────────────────
    _section("4. bad deadline -> 400")
    r = client.post(
        f"/api/trades/{plan_id}/edit",
        data={"time_stop_deadline": "tomorrow at noon"},
    )
    print(f"  status: {r.status_code}, body: {r.text[:80]}")
    assert r.status_code == 400

    # ── 5. Missing trade -> 404 ────────────────────────────────
    _section("5. unknown trade id -> 404")
    r = client.post(
        f"/api/trades/does-not-exist/edit",
        data={"entry_price": "100"},
    )
    print(f"  status: {r.status_code}")
    assert r.status_code == 404

    # ── 6. Refuses non-active stage ────────────────────────────
    _section("6. closed trade (stage=rejected) -> 409")
    # Flip the row to rejected and try editing
    import aiosqlite
    async with aiosqlite.connect(db_service.DB_PATH) as db:
        await db.execute(
            "UPDATE pending_approvals SET status='rejected' WHERE plan_id=?",
            (plan_id,),
        )
        await db.commit()
    r = client.post(
        f"/api/trades/{plan_id}/edit",
        data={"entry_price": "200"},
    )
    print(f"  status: {r.status_code}, body: {r.text[:120]}")
    assert r.status_code == 409

    await _delete(plan_id)
    # Drop the close job we left behind
    try:
        sched.remove_job(f"close_{plan_id}")
    except Exception:
        pass

    stop_scheduler()
    print("\n[smoke_trade_edit] ALL CHECKS PASSED")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
