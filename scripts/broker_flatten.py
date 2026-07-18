"""broker_flatten.py — inspect what the broker ACTUALLY reports, and (optionally)
flatten every open position.

Why this exists: after an IBKR paper reset the app may still show old positions
and a stale equity, because the app mirrors whatever IB Gateway sends. This
prints the broker's ground truth (account values + every position with its
market value) so you can see exactly what the gateway is reporting, and can
flatten if the positions are real.

    python -m scripts.broker_flatten            # DIAGNOSE — print account + positions, no orders
    python -m scripts.broker_flatten --flatten --yes   # close every open position at market

The running app already holds IBKR clientId 7, so this script connects with its
OWN id (default 11) to avoid an "id already in use" clash — no need to stop the
app. Override with --client-id if 11 is taken too.

IMPORTANT: flattening SELLS the positions, so their value moves into CASH — it
does NOT reduce equity. If your equity is inflated by leftover positions and you
want a clean $100k, the fix is to RE-RUN the IBKR paper reset (which removes the
positions), then restart IB Gateway so it re-syncs. Use this tool to confirm
what the gateway is actually holding.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

from services.settings_service import ENV_FILE  # noqa: E402

load_dotenv(ENV_FILE, override=False)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--flatten", action="store_true", help="place closing orders")
    ap.add_argument("--yes", action="store_true", help="required with --flatten")
    ap.add_argument("--client-id", type=int, default=11,
                    help="IBKR API clientId for THIS script (default 11; the app uses 7)")
    args = ap.parse_args()

    # Use a distinct clientId so we don't clash with the running app (clientId 7).
    # IbkrAdapter reads IBKR_CLIENT_ID at build time; build a fresh adapter after.
    os.environ["IBKR_CLIENT_ID"] = str(args.client_id)

    from models.account import Order  # noqa: E402  (imported late, after env set)
    from services import broker_service  # noqa: E402

    adapter = await broker_service.build_adapter()
    if not adapter.connected:
        await adapter.connect()
    if not adapter.connected:
        print("Broker not connected — is IB Gateway up with the API enabled?")
        return
    try:
        await _run(adapter, args, Order)
    finally:
        try:
            await adapter.disconnect()
        except Exception:  # noqa: BLE001
            pass


async def _run(adapter, args, Order) -> None:
    state = await adapter.get_account_state()
    print(f"Broker      : {adapter.broker_name}")
    print(f"Account     : {state.account_id}")
    print(f"Equity      : ${state.equity:,.2f}")
    print(f"Cash        : ${state.cash:,.2f}")
    print(f"Buying power: ${state.buying_power:,.2f}")
    positions = list(state.open_positions)
    print(f"\nOpen positions reported by the broker: {len(positions)}")
    total_mv = 0.0
    for p in positions:
        mv = (p.market_price or 0) * (p.shares or 0)
        total_mv += mv
        print(f"  {p.symbol:8} {p.shares:>7} sh  @ ${(p.avg_entry_price or 0):,.2f} "
              f"→ ${(p.market_price or 0):,.2f}  mktval ${mv:,.2f}  "
              f"uP&L ${(p.unrealized_pnl_usd or 0):,.2f}")
    print(f"\n  positions market value ≈ ${total_mv:,.2f}")
    print(f"  equity − cash          = ${state.equity - state.cash:,.2f}")

    if not positions:
        print("\nBroker is flat. If the app still shows open trades, they're app-side "
              "DB rows — run: python -m scripts.reset_trade_history --yes --close-open")
        return

    if not (args.flatten and args.yes):
        print("\nDiagnostic only. To CLOSE every position at market, re-run with "
              "--flatten --yes.\n(Reminder: flattening moves value into cash; it does "
              "NOT lower equity. For a clean $100k, re-run the IBKR paper reset.)")
        return

    print("\nFlattening all positions at market…")
    ok = fail = 0
    for p in positions:
        shares = abs(int(p.shares or 0))
        if shares == 0:
            continue
        side = "sell" if (p.shares or 0) > 0 else "buy"
        order = Order(
            client_order_id=f"flat-{p.symbol.lower()}-{uuid4().hex[:8]}",
            symbol=p.symbol, side=side, order_type="market",
            quantity=shares, time_in_force="day",
        )
        try:
            ack = await adapter.place_order(order)
            if ack.accepted:
                ok += 1
                print(f"  {p.symbol:8} {side} {shares} → order {ack.broker_order_id}")
            else:
                fail += 1
                print(f"  {p.symbol:8} REJECTED: {ack.reject_reason}")
        except Exception as e:  # noqa: BLE001
            fail += 1
            print(f"  {p.symbol:8} ERROR: {e}")
    print(f"\nFlatten submitted: {ok} ok, {fail} failed. Re-run without flags to "
          "confirm the book is empty.")


if __name__ == "__main__":
    asyncio.run(main())
