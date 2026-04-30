"""scripts/demo_bracket_orders.py — one-off paper trade demo.

Places 4 bracket orders (2 long + 2 short) on the active broker
account so the live status bar has chips to render. Each parent is a
limit order with a small premium/discount to ensure it fills at the
next session open; the bracket attaches a TP at +2% and a hard SL at
-1.5% (sign-flipped for shorts).

This bypasses the agent pipeline — no compliance / risk gates. Demo
only; never run on a live account.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


PLAN = [
    # symbol, side, qty, premium_pct, tp_pct, sl_pct
    ("F",    "long",  1, 0.5, 2.0, 1.5),
    ("T",    "long",  1, 0.5, 2.0, 1.5),
    ("INTC", "short", 1, 0.5, 2.0, 1.5),
    ("BAC",  "short", 1, 0.5, 2.0, 1.5),
]
DEMO_SYMS = {p[0] for p in PLAN}


async def main() -> None:
    from services import broker_service, account_service

    active = await account_service.get_active_account()
    print(f"Active account: {active['label']} ({active['provider']}/{active['account_type']})")
    if active["account_type"] == "live":
        print("REFUSING: active account is LIVE. Switch to a paper account first.")
        return

    adapter = await broker_service.get_adapter_async()
    await broker_service.connect_adapter()

    from alpaca.trading.requests import (
        LimitOrderRequest, TakeProfitRequest, StopLossRequest,
    )
    from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
    from alpaca.data.requests import StockLatestQuoteRequest

    tc = adapter._trading_client  # type: ignore[attr-defined]
    dc = adapter._data_client     # type: ignore[attr-defined]

    # ---- Cancel any pre-existing demo orders ----
    print()
    print("Cancelling pre-existing open orders for demo symbols...")
    try:
        opens = await asyncio.to_thread(tc.get_orders)
        cancelled = 0
        for o in opens:
            if o.symbol in DEMO_SYMS:
                try:
                    await asyncio.to_thread(tc.cancel_order_by_id, order_id=o.id)
                    cancelled += 1
                    print(f"  cancelled {o.symbol} order {str(o.id)[:8]}")
                except Exception as e:                       # noqa: BLE001
                    print(f"  cancel {o.symbol} err: {e}")
        print(f"  total cancelled: {cancelled}")
    except Exception as e:                                    # noqa: BLE001
        print(f"  fetch opens err: {e}")

    # ---- Place 4 bracket orders ----
    print()
    print("Placing 4 bracket orders (limit GTC + bracket TP/SL):")
    for sym, side, qty, prem_pct, tp_pct, sl_pct in PLAN:
        try:
            qreq = StockLatestQuoteRequest(symbol_or_symbols=[sym])
            qres = await asyncio.to_thread(dc.get_stock_latest_quote, qreq)
            q = qres.get(sym)
            if q is None:
                print(f"  {sym}: no quote, skipping")
                continue
            ask = float(getattr(q, "ask_price", 0) or 0)
            bid = float(getattr(q, "bid_price", 0) or 0)
            mid = (ask + bid) / 2 if ask and bid else (ask or bid)
            if mid <= 0:
                print(f"  {sym}: zero quote, skipping")
                continue

            if side == "long":
                limit   = round(mid * (1 + prem_pct / 100), 2)
                tp      = round(limit * (1 + tp_pct / 100), 2)
                sl_stop = round(limit * (1 - sl_pct / 100), 2)
                sl_lim  = round(sl_stop * 0.999, 2)
                alpaca_side = OrderSide.BUY
            else:
                limit   = round(mid * (1 - prem_pct / 100), 2)
                tp      = round(limit * (1 - tp_pct / 100), 2)
                sl_stop = round(limit * (1 + sl_pct / 100), 2)
                sl_lim  = round(sl_stop * 1.001, 2)
                alpaca_side = OrderSide.SELL

            req = LimitOrderRequest(
                symbol=sym,
                qty=qty,
                side=alpaca_side,
                time_in_force=TimeInForce.GTC,
                limit_price=limit,
                order_class=OrderClass.BRACKET,
                take_profit=TakeProfitRequest(limit_price=tp),
                stop_loss=StopLossRequest(stop_price=sl_stop, limit_price=sl_lim),
                client_order_id=f"demo-{sym.lower()}-{uuid4().hex[:8]}",
            )
            r = await asyncio.to_thread(tc.submit_order, order_data=req)
            print(
                f"  {sym:5s}  {side:5s}  qty={qty}  "
                f"entry@${limit:.2f}  TP@${tp:.2f}  SL@${sl_stop:.2f}  "
                f"id={str(r.id)[:8]}  status={r.status}"
            )
        except Exception as e:                                # noqa: BLE001
            print(f"  {sym}: FAILED — {type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
