"""Phase 4 C3 — executioner smoke test.

Walks the full click-path that the UI follows:

  1. Seed a clean, passing paper plan in the DB (AAPL long, 1 share,
     passing both gates) with synthetic verdicts attached.
  2. POST /pending/<id>/ack?action=approve
  3. Executioner re-verifies everything, translates the plan to an
     Order, places it via the Alpaca adapter.
  4. Assert the row is now status='executed' with a broker_order_id.
  5. Fetch Alpaca account state, confirm the AAPL position is open.
  6. Cleanup: sell 1 AAPL to close the position — leaves the paper
     account net-flat.

Also exercises the refusal path:
  7. Seed a research-mode plan, approve it → executioner refuses with
     'research_mode_no_orders'.

Run:
  .venv\\Scripts\\python -m scripts.smoke_phase4_c3_executioner
"""
from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone
from uuid import uuid4

import aiosqlite
from dotenv import load_dotenv

from services.settings_service import ENV_FILE

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

SYMBOL = "AAPL"  # liquid, instant paper fills


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def _build_paper_plan(
    *, plan_id: str, mode: str = "paper", entry: float = 180.0,
) -> dict:
    stop = entry * 0.97
    tp1 = entry * 1.04
    tp2 = entry * 1.08
    r_per_share = entry - stop
    return {
        "plan_id": plan_id,
        "ts_created": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "schema_version": "1.0.0",
        "instrument": {"symbol": SYMBOL, "asset_class": "equity",
                       "exchange": "NASDAQ", "sector": "Technology",
                       "industry": "Consumer Electronics"},
        "thesis": {
            "summary": "C3 smoke — minimal clean paper plan",
            "lenses_contributing": ["technical"],
            "signal_ids": [], "conviction": 0.80,
            "expected_holding_period": "swing_days",
            "similar_past_setups": [], "memory_win_rate": None,
            "memory_avg_r": None,
        },
        "setup": {
            "direction": "long",
            "entry": {"type": "limit", "price": round(entry, 2),
                      "valid_until": "gtc"},
            "take_profit": [
                {"leg": 1, "price": round(tp1, 2), "size_pct": 50,
                 "reason": "tp1"},
                {"leg": 2, "price": round(tp2, 2), "size_pct": 50,
                 "reason": "tp2"},
            ],
            "stop_loss": {
                "initial": {"type": "hard", "price": round(stop, 2),
                            "reason": "pattern_stop"},
                "trail": {"active": True, "activate_after": "1R",
                          "mode": "atr", "atr_multiple": 1.5,
                          "atr_period": 14},
                "time_stop": {"active": True, "condition": "5 sessions",
                              "deadline": "2099-01-01"},
                "thesis_invalidation": {"active": True,
                                        "condition": "daily_close_below_stop"},
            },
        },
        "risk": {
            "r_per_share": round(r_per_share, 2),
            "position_size_shares": 1,
            "position_notional_usd": round(entry, 2),
            "position_risk_usd": round(r_per_share, 2),
            "position_risk_pct_of_equity": 0.005,
            "position_notional_pct_of_equity": 0.18,
            "r_multiple_to_tp1": round((tp1 - entry) / r_per_share, 2),
            "r_multiple_to_tp2": round((tp2 - entry) / r_per_share, 2),
        },
        "execution": {"preferred_algo": "vwap", "participation_cap_pct_adv": 2.0,
                      "max_spread_bps_to_cross": 15, "urgency": "low",
                      "broker": "alpaca_paper", "account_type": mode},
        "evidence": [{"type": "pattern", "ref": "C3 smoke synthetic"}],
        "tradingview_chart_url": (
            f"https://www.tradingview.com/chart/?symbol=NASDAQ:{SYMBOL}&interval=D"
        ),
    }


def _clean_verdicts(plan_id: str, size: int, mode_label: str):
    ts = datetime.now(timezone.utc).isoformat()
    compliance = {
        "verdict_id": f"cv-{plan_id}", "plan_id": plan_id, "ts": ts,
        "result": "approved",
        "gates_evaluated": ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"],
        "gates_failed": [],
    }
    risk = {
        "verdict_id": f"rv-{plan_id}", "plan_id": plan_id, "ts": ts,
        "result": "approved",
        "original_size_shares": size, "approved_size_shares": size,
        "gates_evaluated": ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9"],
        "gates_triggered": [],
        "approved_risk_usd": 0.0, "approved_notional_usd": 0.0,
    }
    return compliance, risk


async def _cleanup_aapl(adapter) -> None:
    """Close any AAPL position the test opened."""
    from models.account import Order

    account = await adapter.get_account_state()
    aapl = next((p for p in account.open_positions if p.symbol == SYMBOL), None)
    if not aapl or aapl.shares == 0:
        return
    sell = Order(
        client_order_id=f"c3-cleanup-{uuid4().hex[:8]}",
        symbol=SYMBOL,
        side="sell" if aapl.shares > 0 else "buy_to_cover",
        order_type="market",
        quantity=abs(aapl.shares),
        time_in_force="day",
    )
    ack = await adapter.place_order(sell)
    if ack.accepted:
        logging.getLogger(__name__).info(
            "cleanup: sold %d AAPL broker_order_id=%s",
            abs(aapl.shares), ack.broker_order_id,
        )
        # Give Alpaca a moment to fill the market order
        for _ in range(20):
            await asyncio.sleep(0.5)
            after = await adapter.get_account_state()
            if not any(p.symbol == SYMBOL and p.shares != 0
                       for p in after.open_positions):
                return


async def main() -> int:
    load_dotenv(ENV_FILE, override=False)

    import httpx
    import uvicorn

    from brokers.alpaca import AlpacaAdapter
    from services import db_service

    print("=" * 78)
    print("Phase 4 C3 smoke test — executioner end-to-end")
    print("=" * 78)

    await db_service.ensure_tables()

    # Clean slate so plan_ids are predictable
    async with aiosqlite.connect(db_service.DB_PATH) as db:
        await db.execute(
            "DELETE FROM pending_approvals WHERE plan_id LIKE 'c3-smoke-%'",
        )
        await db.commit()

    # ---- 1. Seed a clean paper plan ------------------------------------
    print("\n[1/7] Seed clean paper plan (c3-smoke-paper, AAPL long 1 share)")
    paper_plan_id = "c3-smoke-paper"
    paper_plan = _build_paper_plan(plan_id=paper_plan_id)
    compliance, risk = _clean_verdicts(paper_plan_id, size=1, mode_label="paper")
    await db_service.upsert_pending_plan(
        paper_plan,
        compliance_verdict=compliance, risk_verdict=risk,
        status="pending", strategy="smoke",
    )
    print("  OK — row inserted")

    # ---- 2. Seed a research-mode plan to exercise the refusal path -----
    print("\n[2/7] Seed research-mode plan (c3-smoke-research — must refuse)")
    research_plan_id = "c3-smoke-research"
    research_plan = _build_paper_plan(plan_id=research_plan_id, mode="research")
    comp_r, risk_r = _clean_verdicts(research_plan_id, size=1, mode_label="research")
    await db_service.upsert_pending_plan(
        research_plan,
        compliance_verdict=comp_r, risk_verdict=risk_r,
        status="pending", strategy="smoke",
    )
    print("  OK — row inserted")

    # ---- 3. Boot the app -----------------------------------------------
    print("\n[3/7] Boot app on :5059")
    config = uvicorn.Config(
        "app:app", host="127.0.0.1", port=5059, log_level="warning",
    )
    server = uvicorn.Server(config)
    serve_task = asyncio.create_task(server.serve())
    for _ in range(40):
        await asyncio.sleep(0.25)
        if server.started:
            break

    try:
        async with httpx.AsyncClient(
            base_url="http://127.0.0.1:5059", timeout=30,
        ) as c:
            # ---- 4. Approve the research plan → must refuse ------------
            print("\n[4/7] POST /ack approve on research plan — must refuse")
            r = await c.post(
                f"/pending/{research_plan_id}/ack",
                data={"action": "approve"},
            )
            expect(r.status_code == 400,
                   f"expected 400 on research refuse, got {r.status_code}")
            expect("research_mode_no_orders" in r.text,
                   f"body missing reason: {r.text}")
            row = await db_service.get_plan_by_id(research_plan_id)
            expect(row["status"] == "order_rejected",
                   f"expected order_rejected, got {row['status']}")
            expect(row["execution_reject_reason"] == "research_mode_no_orders",
                   f"reject_reason mismatch: {row['execution_reject_reason']}")
            print("  OK — executioner refused research order (stored)")

            # ---- 5. Approve the paper plan → must place ---------------
            print("\n[5/7] POST /ack approve on paper plan — must place")
            r = await c.post(
                f"/pending/{paper_plan_id}/ack",
                data={"action": "approve"},
            )
            expect(r.status_code == 200,
                   f"expected 200 on paper approve, got {r.status_code}: {r.text}")
            expect("Order placed" in r.text, f"body missing ok toast: {r.text}")
            row = await db_service.get_plan_by_id(paper_plan_id)
            expect(row["status"] == "executed",
                   f"expected status=executed, got {row['status']}")
            expect(row["broker_order_id"], "broker_order_id missing on executed row")
            print(f"  OK — plan status=executed broker_order_id={row['broker_order_id']}")

            # ---- 6. Verify position at the broker ----------------------
            print("\n[6/7] Alpaca paper account now shows the AAPL position")
            adapter = AlpacaAdapter(paper=True)
            await adapter.connect()
            # The limit order may sit as OPEN (unfilled) since we placed at
            # current price - $0.02 or so; either way the test verifies the
            # ORDER was placed. We check open orders + positions.
            from alpaca.trading.enums import QueryOrderStatus
            from alpaca.trading.requests import GetOrdersRequest
            def _sync_orders():
                return adapter._trading_client.get_orders(
                    filter=GetOrdersRequest(status=QueryOrderStatus.OPEN),
                )
            open_orders = await asyncio.to_thread(_sync_orders)
            found = any(
                str(o.id) == row["broker_order_id"]
                or getattr(o, "client_order_id", None) == (
                    row["execution"].get("client_order_id") if row["execution"] else None
                )
                for o in open_orders
            )
            account = await adapter.get_account_state()
            pos = next((p for p in account.open_positions if p.symbol == SYMBOL), None)
            print(
                f"  broker_order_id {row['broker_order_id']}: "
                f"{'in open_orders' if found else 'not in open_orders'}"
            )
            if pos:
                print(f"  account has {pos.shares} AAPL @ ${pos.avg_entry_price:.2f}")
            else:
                print("  no AAPL position yet (limit order still resting)")
            # We accept EITHER outcome — what we assert is that the order
            # exists at the broker somehow. For a limit at entry=$180 with
            # AAPL trading ~$230, the order will rest open until cancelled.
            expect(found or pos is not None,
                   "neither open order nor position found for the approved plan")
            print("  OK — broker state reflects the approved plan")

            # ---- 7. Cleanup: cancel our resting order -----------------
            print("\n[7/7] Cleanup: cancel our resting order + flatten any position")
            if row["broker_order_id"] and found:
                try:
                    await adapter.cancel_order(row["broker_order_id"])
                    print(f"  cancelled {row['broker_order_id']}")
                except Exception as e:  # noqa: BLE001
                    print(f"  cancel raised (ignored): {e}")
            await _cleanup_aapl(adapter)
            await adapter.disconnect()
            print("  OK — cleaned up")

    finally:
        server.should_exit = True
        await serve_task

    print("\n" + "=" * 78)
    print("ALL GREEN — executioner wired end-to-end through the broker.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
