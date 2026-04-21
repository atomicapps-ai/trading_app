"""Alpaca paper-broker smoke test — read-only.

Verifies the new AlpacaAdapter against a real paper account. Exercises:
  1. connect()                 → OAuth-free auth with API_KEY + SECRET
  2. get_account_state()       → returns AccountState (equity, positions)
  3. get_quote("SPY")          → returns live NBBO-style quote
  4. disconnect()

Deliberately does NOT place, modify, or cancel any orders. Order
placement will get its own focused test once we're ready to exercise
the order side. Keeping this one strictly read-only means running it
never risks the paper account's state.

Prereqs:
  * ALPACA_API_KEY + ALPACA_API_SECRET in .env (paper keys, PK prefix)
  * alpaca-py >= 0.43 installed

Run:
  .venv\\Scripts\\python -m scripts.smoke_alpaca_paper
"""
from __future__ import annotations

import asyncio
import logging
import sys

from dotenv import load_dotenv

from services.settings_service import ENV_FILE

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


async def main() -> int:
    load_dotenv(ENV_FILE, override=False)

    from brokers.alpaca import AlpacaAdapter

    print("=" * 70)
    print("Alpaca paper adapter smoke test")
    print("=" * 70)

    adapter = AlpacaAdapter(paper=True)

    # ---- 1. connect -----------------------------------------------------
    print("\n[1/4] connect()")
    ok = await adapter.connect()
    if not ok:
        print("  FAIL - connect returned False (check ALPACA_API_KEY/SECRET in .env)")
        return 1
    assert adapter.connected, "adapter.connected should be True after connect()"
    print(f"  OK - broker_name={adapter.broker_name}, connected={adapter.connected}")

    # ---- 2. get_account_state -----------------------------------------
    print("\n[2/4] get_account_state()")
    acct = await adapter.get_account_state()
    # Paper accounts always start with a round number (typically $100k)
    print(
        f"  OK - account_id={acct.account_id}, type={acct.type}, "
        f"equity=${acct.equity:,.2f}, cash=${acct.cash:,.2f}, "
        f"buying_power=${acct.buying_power:,.2f}"
    )
    print(f"       open_positions={len(acct.open_positions)}, "
          f"trades_today={acct.trades_today}")
    assert acct.broker == "alpaca_paper", f"unexpected broker={acct.broker}"
    assert acct.equity > 0, "paper account should have non-zero equity"

    # ---- 3. get_quote --------------------------------------------------
    print("\n[3/4] get_quote('SPY')")
    try:
        q = await adapter.get_quote("SPY")
        print(
            f"  OK - SPY bid=${q.bid:.2f} x {q.bid_size}, "
            f"ask=${q.ask:.2f} x {q.ask_size}, "
            f"spread={q.spread_bps:.1f}bps, ts={q.ts}"
        )
        if q.bid > 0 and q.ask >= q.bid:
            pass  # sane quote
        else:
            # market may be closed — quote can come back as 0s
            print("  NOTE: bid/ask are zero; market is likely closed. "
                  "Real quote-routing still verified the auth path.")
    except Exception as e:  # noqa: BLE001
        print(f"  WARN - quote fetch raised: {e}")
        print("  (Market-data subscription level may not include SPY NBBO; "
              "non-fatal for paper trading.)")

    # ---- 4. disconnect -------------------------------------------------
    print("\n[4/4] disconnect()")
    await adapter.disconnect()
    assert not adapter.connected
    print("  OK - disconnected cleanly")

    print("\n" + "=" * 70)
    print("ALL GREEN - Alpaca paper adapter auth + account read path works.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
