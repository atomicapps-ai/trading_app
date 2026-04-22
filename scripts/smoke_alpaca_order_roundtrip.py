"""Alpaca paper order round-trip smoke test.

Exercises the FULL order lifecycle on a real paper account:

  1. Snapshot the account (pre-trade)
  2. Place a BUY market order for 1 share of SPY
  3. Poll until the order fills
  4. Snapshot again (should show 1 SPY position)
  5. Place a SELL market order for 1 share of SPY (closes the position)
  6. Poll until that fills
  7. Final snapshot (position closed, cash roughly unchanged)
  8. Print realized P&L for the round-trip

This is the real paper account's state-changing test. It leaves the
account net-flat afterward, but between steps 2 and 5 a real paper
position will be open. No margin concerns at 1 share × SPY ≈ $706.

Run:
  .venv\\Scripts\\python -m scripts.smoke_alpaca_order_roundtrip
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from uuid import uuid4

from dotenv import load_dotenv

from services.settings_service import ENV_FILE

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


SYMBOL = "SPY"
QTY = 1
POLL_INTERVAL_SECONDS = 1.0
POLL_TIMEOUT_SECONDS = 30.0


async def _wait_for_fill(adapter, client_order_id: str, broker_order_id: str) -> dict | None:
    """Poll the Alpaca order status until filled, cancelled, or timeout.

    Returns the filled order dict (or None on timeout).
    """
    import asyncio as _asyncio

    from alpaca.trading.enums import QueryOrderStatus
    from alpaca.trading.requests import GetOrdersRequest

    deadline = time.time() + POLL_TIMEOUT_SECONDS
    while time.time() < deadline:
        def _get():
            return adapter._trading_client.get_order_by_id(order_id=broker_order_id)
        try:
            o = await _asyncio.to_thread(_get)
        except Exception as e:  # noqa: BLE001
            print(f"  poll error: {e}")
            return None
        status = str(o.status).lower()
        if "filled" in status or status == "filled":
            return o
        if status in ("canceled", "cancelled", "rejected", "expired"):
            print(f"  order terminated with status={status}")
            return o
        await _asyncio.sleep(POLL_INTERVAL_SECONDS)
    print("  timeout waiting for fill")
    return None


async def main() -> int:
    load_dotenv(ENV_FILE, override=False)

    from brokers.alpaca import AlpacaAdapter
    from models.account import Order

    print("=" * 78)
    print(f"Alpaca paper round-trip: BUY 1 {SYMBOL} -> SELL 1 {SYMBOL}")
    print("=" * 78)

    adapter = AlpacaAdapter(paper=True)
    ok = await adapter.connect()
    if not ok:
        print("FAIL — could not connect to Alpaca paper")
        return 1

    # ---- pre-trade snapshot --------------------------------------------
    print("\n[1/8] Pre-trade account snapshot")
    pre = await adapter.get_account_state()
    print(f"  equity=${pre.equity:,.2f}  cash=${pre.cash:,.2f}  "
          f"positions={len(pre.open_positions)}")

    # ---- BUY --------------------------------------------------------
    buy_coid = f"smoke-buy-{uuid4().hex[:8]}"
    buy = Order(
        client_order_id=buy_coid,
        symbol=SYMBOL,
        side="buy",
        order_type="market",
        quantity=QTY,
        time_in_force="day",
    )
    print(f"\n[2/8] Placing BUY {QTY} {SYMBOL} market (client_order_id={buy_coid})")
    ack = await adapter.place_order(buy)
    if not ack.accepted:
        print(f"  BUY rejected: {ack.reject_reason}")
        await adapter.disconnect()
        return 1
    print(f"  OK — accepted, broker_order_id={ack.broker_order_id}")

    # ---- wait for fill ------------------------------------------------
    print("\n[3/8] Polling for fill...")
    buy_order = await _wait_for_fill(adapter, buy_coid, ack.broker_order_id)
    if buy_order is None or "filled" not in str(buy_order.status).lower():
        print("  FAIL — BUY did not fill in time; market may be closed")
        print("  (Alpaca paper does fill market orders instantly during market hours)")
        await adapter.disconnect()
        return 1
    buy_fill_price = float(getattr(buy_order, "filled_avg_price", 0) or 0)
    print(f"  OK — filled at ${buy_fill_price:.2f} x {QTY}")

    # ---- post-BUY snapshot --------------------------------------------
    print("\n[4/8] Post-BUY account snapshot")
    mid = await adapter.get_account_state()
    pos_sym = next((p for p in mid.open_positions if p.symbol == SYMBOL), None)
    if pos_sym is None:
        print(f"  WARN — no {SYMBOL} position returned by account snapshot")
    else:
        print(f"  {SYMBOL}: {pos_sym.shares} shares @ ${pos_sym.avg_entry_price:.2f} "
              f"(market=${pos_sym.market_price:.2f}, "
              f"unrealized=${pos_sym.unrealized_pnl_usd:.2f})")

    # ---- SELL -------------------------------------------------------
    sell_coid = f"smoke-sell-{uuid4().hex[:8]}"
    sell = Order(
        client_order_id=sell_coid,
        symbol=SYMBOL,
        side="sell",
        order_type="market",
        quantity=QTY,
        time_in_force="day",
    )
    print(f"\n[5/8] Placing SELL {QTY} {SYMBOL} market (client_order_id={sell_coid})")
    sell_ack = await adapter.place_order(sell)
    if not sell_ack.accepted:
        print(f"  SELL rejected: {sell_ack.reject_reason}")
        await adapter.disconnect()
        return 1
    print(f"  OK — accepted, broker_order_id={sell_ack.broker_order_id}")

    print("\n[6/8] Polling for SELL fill...")
    sell_order = await _wait_for_fill(adapter, sell_coid, sell_ack.broker_order_id)
    if sell_order is None or "filled" not in str(sell_order.status).lower():
        print("  FAIL — SELL did not fill")
        await adapter.disconnect()
        return 1
    sell_fill_price = float(getattr(sell_order, "filled_avg_price", 0) or 0)
    print(f"  OK — filled at ${sell_fill_price:.2f} x {QTY}")

    # ---- final snapshot -----------------------------------------------
    print("\n[7/8] Final account snapshot (should be flat)")
    post = await adapter.get_account_state()
    still_open = next((p for p in post.open_positions if p.symbol == SYMBOL), None)
    if still_open:
        print(f"  WARN — {SYMBOL} still open: {still_open.shares} shares")
    else:
        print(f"  OK — no {SYMBOL} position, account is flat")
    print(f"  equity=${post.equity:,.2f}  cash=${post.cash:,.2f}  "
          f"positions={len(post.open_positions)}")

    # ---- round-trip P&L -----------------------------------------------
    gross_pnl = (sell_fill_price - buy_fill_price) * QTY
    print("\n[8/8] Round-trip P&L")
    print(f"  BUY  @ ${buy_fill_price:.2f}")
    print(f"  SELL @ ${sell_fill_price:.2f}")
    print(f"  Gross P&L on {QTY} share: ${gross_pnl:+.2f}  "
          f"(commission on stocks/ETFs = $0.00 on Alpaca)")

    await adapter.disconnect()

    print("\n" + "=" * 78)
    print("ALL GREEN — round-trip paper order lifecycle works end-to-end.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
