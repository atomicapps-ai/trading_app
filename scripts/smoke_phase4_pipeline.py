"""Phase 4 C2 — pipeline_service + db_service smoke test.

Exercises:
  1. ensure_tables() — creates pending_approvals / pipeline_runs /
     trade_memory + indexes idempotently.
  2. run_workflow_by_id('research_run') — engine emits plans,
     compliance + risk gates run on every plan, verdicts persisted.
  3. get_pending_plans() returns rows shaped for the /pending template.
  4. /pending HTTP route reads from SQLite (boot the app, GET /pending,
     assert pending count >= 1 if the pipeline produced any).
  5. ack flow: POST /pending/{id}/ack transitions the row's status.

Run:
  .venv\\Scripts\\python -m scripts.smoke_phase4_pipeline
"""
from __future__ import annotations

import asyncio
import logging
import sys

from dotenv import load_dotenv

from services.settings_service import ENV_FILE

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


async def main() -> int:
    load_dotenv(ENV_FILE, override=False)

    from services import db_service, pipeline_service

    print("=" * 78)
    print("Phase 4 C2 smoke test — pipeline_service + db_service")
    print("=" * 78)

    # ---- 1. ensure_tables ----------------------------------------------
    print("\n[1/5] ensure_tables()")
    await db_service.ensure_tables()
    print(f"  OK — DB at {db_service.DB_PATH}")

    # Clean slate: wipe any pending rows from a previous run
    import aiosqlite
    async with aiosqlite.connect(db_service.DB_PATH) as conn:
        await conn.execute("DELETE FROM pending_approvals")
        await conn.execute("DELETE FROM pipeline_runs")
        await conn.commit()

    # ---- 2. run pipeline -----------------------------------------------
    print("\n[2/5] pipeline_service.run_workflow_by_id('research_run')")
    summary = await pipeline_service.run_workflow_by_id("research_run")
    expect(summary["error"] is None, f"run errored: {summary['error']}")
    print(
        f"  OK — run_id={summary['run_id']}, "
        f"proposed={summary['plans_proposed']}, "
        f"approved={summary['plans_approved']}, "
        f"blocked={len(summary['plans_blocked'])}, "
        f"{summary['duration_seconds']:.2f}s"
    )
    for b in summary["plans_blocked"]:
        print(f"    blocked: {b['symbol']} by {b['gate']} ({b['reason']})")

    # ---- 3. DB rows reflect the run ------------------------------------
    print("\n[3/5] SQLite rows")
    pending_rows = await db_service.get_pending_plans(status_filter="pending")
    rejected_rows = await db_service.get_pending_plans(status_filter="rejected")
    runs = await db_service.list_pipeline_runs(limit=5)

    expect(len(runs) == 1, f"expected 1 pipeline_runs row, got {len(runs)}")
    row = runs[0]
    expect(row["run_id"] == summary["run_id"], "run_id mismatch")
    expect(row["plans_proposed"] == summary["plans_proposed"], "plans_proposed mismatch")
    print(f"  pipeline_runs: 1 row (status={row['status']})")
    print(f"  pending_approvals: {len(pending_rows)} pending, {len(rejected_rows)} rejected")

    total_written = len(pending_rows) + len(rejected_rows)
    expect(total_written == summary["plans_proposed"],
           f"DB total ({total_written}) != plans_proposed ({summary['plans_proposed']})")

    # Spot-check the shape of a pending row (what /pending template expects)
    if pending_rows:
        p = pending_rows[0]
        for k in ("plan_id", "symbol", "direction", "entry", "stop",
                  "tp1", "tp2", "position_size", "conviction"):
            expect(k in p, f"pending row missing {k!r}")
        print(f"  sample pending: {p['symbol']} {p['direction']} "
              f"{p['position_size']}sh entry=${p['entry']} tp1=${p['tp1']} "
              f"R_tp1={p['rr_tp1']}")

    # ---- 4. HTTP surface -----------------------------------------------
    print("\n[4/5] HTTP /pending + /api/pending/count")
    # Boot app in-process
    import uvicorn
    import httpx

    config = uvicorn.Config(
        "app:app", host="127.0.0.1", port=5058, log_level="warning",
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    # Wait for the server to come up
    for _ in range(40):
        await asyncio.sleep(0.25)
        if server.started:
            break

    try:
        async with httpx.AsyncClient(base_url="http://127.0.0.1:5058", timeout=10) as c:
            r = await c.get("/pending")
            expect(r.status_code == 200, f"/pending: {r.status_code}")
            html = r.text
            # Rough content check: page should mention "Pending"
            expect("pending" in html.lower(), "/pending body missing expected text")

            r = await c.get("/api/pending/count")
            expect(r.status_code == 200, f"/api/pending/count: {r.status_code}")
            count = int(r.text.strip())
            expect(count == len(pending_rows),
                   f"count mismatch: HTTP={count} DB={len(pending_rows)}")
            print(f"  OK — /pending=200, /api/pending/count={count}")

            # ---- 5. ack flow -------------------------------------------
            # If the live pipeline didn't produce a pending row (happens
            # when detectors fire plans the gates then reject — correct
            # behaviour), insert a synthetic pending plan so we can still
            # exercise the ack path end-to-end.
            if not pending_rows:
                synthetic_plan = {
                    "plan_id": "smoke-c2-synthetic",
                    "ts_created": "2026-04-21T12:00:00+00:00",
                    "mode": "paper",
                    "schema_version": "1.0.0",
                    "instrument": {"symbol": "AAPL", "asset_class": "equity",
                                   "exchange": "NASDAQ", "sector": "Technology",
                                   "industry": "Consumer Electronics"},
                    "thesis": {"summary": "synthetic for ack test",
                               "lenses_contributing": ["technical"],
                               "signal_ids": [], "conviction": 0.70,
                               "expected_holding_period": "swing_days",
                               "similar_past_setups": [], "memory_win_rate": None,
                               "memory_avg_r": None},
                    "setup": {
                        "direction": "long",
                        "entry": {"type": "limit", "price": 200.0,
                                  "valid_until": "gtc"},
                        "take_profit": [
                            {"leg": 1, "price": 210.0, "size_pct": 50,
                             "reason": "tp1"},
                            {"leg": 2, "price": 220.0, "size_pct": 50,
                             "reason": "tp2"},
                        ],
                        "stop_loss": {
                            "initial": {"type": "hard", "price": 195.0,
                                        "reason": "below_pivot"},
                            "trail": {"active": True,
                                      "activate_after": "price >= entry + 1R",
                                      "mode": "atr", "atr_multiple": 1.5,
                                      "atr_period": 14},
                            "time_stop": {"active": True,
                                          "condition": "no progress",
                                          "deadline": "2099-01-01"},
                            "thesis_invalidation": {"active": True,
                                                    "condition": "below_pivot"},
                        },
                    },
                    "risk": {"r_per_share": 5.0, "position_size_shares": 100,
                             "position_notional_usd": 20000.0,
                             "position_risk_usd": 500.0,
                             "position_risk_pct_of_equity": 0.5,
                             "position_notional_pct_of_equity": 20.0,
                             "r_multiple_to_tp1": 2.0,
                             "r_multiple_to_tp2": 4.0},
                    "execution": {"preferred_algo": "vwap",
                                  "participation_cap_pct_adv": 2.0,
                                  "max_spread_bps_to_cross": 15,
                                  "urgency": "low",
                                  "broker": "alpaca_paper",
                                  "account_type": "paper"},
                    "evidence": [],
                    "tradingview_chart_url": "",
                }
                await db_service.upsert_pending_plan(
                    synthetic_plan, status="pending", strategy="synthetic",
                )
                pending_rows = await db_service.get_pending_plans(
                    status_filter="pending",
                )

            p = pending_rows[0]
            ack_url = f"/pending/{p['plan_id']}/ack"
            r = await c.post(ack_url, data={"action": "approve"})
            expect(r.status_code == 200, f"ack: {r.status_code}")
            # Confirm status flipped
            after = await db_service.get_plan_by_id(p["plan_id"])
            expect(after is not None, "plan disappeared after ack")
            expect(after["status"] == "approved",
                   f"status not approved: {after['status']}")
            expect(after["ack_action"] == "approve",
                   f"ack_action: {after['ack_action']}")
            print(f"  OK - /pending/.../ack flipped status "
                  f"{p['status']!r} -> {after['status']!r}")

    finally:
        server.should_exit = True
        await task

    print("\n" + "=" * 78)
    print("ALL GREEN — pipeline_service + db_service wired end-to-end.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
