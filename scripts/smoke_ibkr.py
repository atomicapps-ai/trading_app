"""smoke_ibkr.py — verify the IBKR adapter against a running IB Gateway/TWS.

Run this on the machine where IB Gateway (or TWS) is running with the API
enabled. It exercises the read paths (connect, account, quotes for a stock +
FX pair + spot gold) and, with --order, a tiny paper order round-trip.

    # read-only checks against paper gateway (port 4002)
    python -m scripts.smoke_ibkr

    # also place + cancel a 1-share AAPL paper order (PAPER ONLY)
    python -m scripts.smoke_ibkr --order

    # point at TWS paper instead of Gateway
    python -m scripts.smoke_ibkr --port 7497

Nothing here touches the app's DB or singletons — it builds a throwaway
IbkrAdapter so you can confirm connectivity before flipping the app over.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from brokers.ibkr import IbkrAdapter
from models.account import Order


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default=None, help="gateway host (default IBKR_HOST or 127.0.0.1)")
    ap.add_argument("--port", type=int, default=None,
                    help="gateway port (default 4002 paper; 4001 live, 7497/7496 TWS)")
    ap.add_argument("--live", action="store_true",
                    help="connect to the LIVE port (4001) instead of paper")
    ap.add_argument("--order", action="store_true",
                    help="also place + cancel a 1-share AAPL paper order")
    ap.add_argument("--client-id", type=int, default=None,
                    help="override IBKR client id (try a fresh one if the "
                         "handshake hangs — a stale connection may hold the default)")
    a = ap.parse_args()

    paper = not a.live
    adapter = IbkrAdapter(paper=paper, host=a.host, port=a.port,
                          client_id=a.client_id)
    host, port = adapter._host, adapter._port

    # Raw TCP preflight — distinguishes the failure modes BEFORE the API layer:
    #   OPEN    → the port is reachable; any hang after this is the API
    #             handshake (settings not applied, or a hidden accept dialog).
    #   REFUSED → nothing is listening on this port (Gateway not bound here /
    #             not running / wrong port / a second app grabbed it).
    #   TIMEOUT → packets are being dropped → a firewall (e.g. TinyWall) is
    #             blocking THIS client (.venv python.exe), not just the server.
    import socket
    print(f"→ TCP preflight to {host}:{port} …")
    sk = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sk.settimeout(4)
    try:
        sk.connect((host, port))
        print(f"  TCP: OPEN — the port is reachable.")
    except socket.timeout:
        print(f"  TCP: TIMEOUT — packets dropped → firewall is blocking this "
              f"client. Allow {sys.executable} in TinyWall (or disable it to test).")
        return 2
    except ConnectionRefusedError:
        print(f"  TCP: REFUSED — nothing is listening on {port}. Is Gateway on "
              f"this exact port, applied + restarted? (paper Gateway = 4002)")
        return 2
    except Exception as e:  # noqa: BLE001
        print(f"  TCP: error {e}")
    finally:
        sk.close()

    print(f"→ connecting to {host}:{port} ({'paper' if paper else 'LIVE'})…")
    print("  (if this hangs ~10s then times out with TCP OPEN above, look for a "
          "hidden 'Accept incoming connection' popup in IB Gateway)")
    try:
        await adapter.connect()
    except Exception as e:  # noqa: BLE001
        print(f"✗ connect failed: {e}")
        print("  Is IB Gateway/TWS running with 'Enable ActiveX and Socket "
              "Clients' ON, and this port correct?")
        return 1
    if not adapter.connected:
        print("✗ not connected"); return 1
    print(f"✓ connected as {adapter.broker_name}")

    # Account
    try:
        acct = await adapter.get_account_state()
        print(f"✓ account: equity=${acct.equity:,.2f} cash=${acct.cash:,.2f} "
              f"buying_power=${acct.buying_power:,.2f} positions={len(acct.open_positions)}")
        for p in acct.open_positions[:10]:
            print(f"    {p.symbol}: {p.shares} @ {p.avg_entry_price} "
                  f"(mkt {p.market_price}, uPnL {p.unrealized_pnl_usd})")
    except Exception as e:  # noqa: BLE001
        print(f"✗ get_account_state failed: {e}")

    # Quotes across all three asset classes the app trades via IBKR.
    for sym in ("AAPL", "EURUSD", "XAUUSD"):
        try:
            q = await adapter.get_quote(sym)
            print(f"✓ quote {sym:7s} bid={q.bid} ask={q.ask}")
        except Exception as e:  # noqa: BLE001
            print(f"✗ quote {sym} failed: {e}")

    # Optional tiny order round-trip (paper only).
    if a.order:
        if not paper:
            print("✗ refusing --order on a LIVE connection");
        else:
            try:
                o = Order(client_order_id="smoke-ibkr-aapl", symbol="AAPL",
                          side="buy", order_type="market", quantity=1,
                          time_in_force="day")
                ack = await adapter.place_order(o)
                print(f"{'✓' if ack.accepted else '✗'} place_order: accepted={ack.accepted} "
                      f"id={ack.broker_order_id} reason={ack.reject_reason or ''}")
                if ack.accepted and ack.broker_order_id:
                    await asyncio.sleep(1)
                    cx = await adapter.cancel_order(ack.broker_order_id)
                    print(f"{'✓' if cx.accepted else '✗'} cancel_order: accepted={cx.accepted}")
            except Exception as e:  # noqa: BLE001
                print(f"✗ order round-trip failed: {e}")

    await adapter.disconnect()
    print("✓ done")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
