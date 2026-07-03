"""ibkr.py — Interactive Brokers adapter (FX + futures + stocks) via ib_insync.

SKELETON on the BrokerAdapter seam. IBKR's API is NOT a cloud REST endpoint: it talks
to a LOCAL gateway you must run — IB Gateway (headless) or TWS — with "Enable ActiveX
and Socket Clients" turned on. This adapter connects to that gateway over a socket.

Ports (IBKR defaults):
    IB Gateway  paper 4002   live 4001
    TWS         paper 7497   live 7496

Env (.env) — connection params only; IBKR auth is the gateway login, NOT API keys:
    IBKR_HOST        127.0.0.1
    IBKR_PORT        4002        (paper IB Gateway by default)
    IBKR_CLIENT_ID   7           (any unique int per connection)

Dependency:  pip install ib_insync   (or the maintained fork: pip install ib_async)
Run the gateway, enable the API, then smoke connect()/get_account_state() on the
PAPER port before any live use.

Asset routing (_contract):
    * 6-letter alpha  -> Forex (IDEALPRO), units = quantity
    * SYM=FUT:EXCH:YYYYMM -> Future
    * otherwise        -> Stock (SMART/USD)
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from brokers.base import BrokerAdapter, BrokerConnectionError
from models.account import AccountState, Fill, Order, OrderAck, Position, Quote

logger = logging.getLogger(__name__)

# ib_insync's eventkit calls asyncio.get_event_loop() at IMPORT time. On
# Python 3.14 that raises RuntimeError when no event loop yet exists in the
# thread — which happens for a plain `python -m scripts.smoke_ibkr` (the
# import runs before asyncio.run). Under uvicorn a loop already exists, so the
# app is fine; this guard makes standalone/CLI imports work too.
import asyncio as _asyncio  # noqa: E402
try:
    _asyncio.get_event_loop()
except RuntimeError:
    _asyncio.set_event_loop(_asyncio.new_event_loop())

# ib_insync (original) or ib_async (maintained fork) — import whichever is present.
try:
    from ib_insync import (IB, Contract, Forex, Stock, Future,  # type: ignore
                           MarketOrder, LimitOrder, StopOrder)
    _IB_LIB = "ib_insync"
except ImportError:  # pragma: no cover
    try:
        from ib_async import (IB, Contract, Forex, Stock, Future,  # type: ignore
                              MarketOrder, LimitOrder, StopOrder)
        _IB_LIB = "ib_async"
    except ImportError:
        IB = None  # type: ignore
        _IB_LIB = None

# Spot metals trade as CMDTY on IBKR (XAUUSD = gold), NOT forex — must be
# routed before the 6-alpha forex rule or XAUUSD wrongly becomes a Forex pair.
_METALS = {"XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD"}


class IbkrAdapter(BrokerAdapter):
    def __init__(self, *, paper: bool = True, host: str | None = None,
                 port: int | None = None, client_id: int | None = None,
                 label: str | None = None):
        self._paper = paper
        self._host = host or os.getenv("IBKR_HOST", "127.0.0.1")
        default_port = 4002 if paper else 4001
        self._port = int(port or os.getenv("IBKR_PORT", str(default_port)))
        self._client_id = int(client_id or os.getenv("IBKR_CLIENT_ID", "7"))
        self._label = label or f"ibkr_{'paper' if paper else 'live'}"
        self._ib = IB() if IB is not None else None

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _contract(self, symbol: str):
        s = symbol.upper().replace("/", "")
        if s.startswith("FUT:") or "=FUT:" in s:          # SYM=FUT:EXCH:YYYYMM
            body = s.split("FUT:", 1)[1]
            sym, exch, expiry = (body.split(":") + ["", ""])[:3]
            sym = sym or s.split("=")[0]
            return Future(sym, expiry, exch or "GLOBEX")
        if s in _METALS:                                   # spot gold/silver etc.
            return Contract(secType="CMDTY", symbol=s, exchange="SMART",
                            currency="USD")
        if len(s) == 6 and s.isalpha():                    # FX pair
            return Forex(s)
        return Stock(s, "SMART", "USD")

    # ── connection ───────────────────────────────────────────────────
    async def connect(self) -> bool:
        if self._ib is None:
            raise BrokerConnectionError("ib_insync not installed — pip install ib_insync")
        try:
            await self._ib.connectAsync(self._host, self._port, clientId=self._client_id, timeout=10)
            logger.info("IBKR connected (%s) %s:%s clientId=%s via %s",
                        self._label, self._host, self._port, self._client_id, _IB_LIB)
            return self._ib.isConnected()
        except Exception as e:  # noqa: BLE001
            raise BrokerConnectionError(
                f"IBKR connect failed ({self._host}:{self._port}). Is IB Gateway/TWS "
                f"running with the API enabled on this port? {e}") from e

    async def disconnect(self) -> None:
        if self._ib is not None and self._ib.isConnected():
            self._ib.disconnect()

    @property
    def connected(self) -> bool:
        return self._ib is not None and self._ib.isConnected()

    @property
    def broker_name(self) -> str:
        return self._label

    # ── account ──────────────────────────────────────────────────────
    async def get_account_state(self) -> AccountState:
        summ = {r.tag: r.value for r in await self._ib.accountSummaryAsync()}
        # portfolio() carries marketPrice + unrealizedPNL per position; plain
        # positions() does not. Fall back to positions() if the portfolio is
        # empty (e.g. brand-new session before it populates).
        portfolio = self._ib.portfolio()
        positions: list[Position] = []
        if portfolio:
            for it in portfolio:
                if it.position == 0:
                    continue
                c = it.contract
                sym = c.symbol + (c.currency if c.secType in ("CASH", "CMDTY") else "")
                positions.append(Position(
                    symbol=sym, shares=int(it.position),
                    avg_entry_price=float(it.averageCost or 0),
                    market_price=float(it.marketPrice or 0),
                    unrealized_pnl_usd=float(it.unrealizedPNL or 0),
                ))
        else:
            for p in self._ib.positions():
                if p.position == 0:
                    continue
                c = p.contract
                sym = c.symbol + (c.currency if c.secType in ("CASH", "CMDTY") else "")
                positions.append(Position(
                    symbol=sym, shares=int(p.position),
                    avg_entry_price=float(p.avgCost or 0), market_price=0.0,
                    unrealized_pnl_usd=0.0,
                ))
        f = lambda k: float(summ.get(k, 0) or 0)  # noqa: E731
        return AccountState(
            account_id=summ.get("AccountType", self._label), broker=self._label, type="margin",
            equity=f("NetLiquidation"), cash=f("TotalCashValue"),
            buying_power=f("BuyingPower"), open_positions=positions,
            unrealized_pnl_today=f("UnrealizedPnL"), trading_halted=False,
            ts_snapshot=self._now(),
        )

    # ── market data ──────────────────────────────────────────────────
    async def get_quote(self, symbol: str) -> Quote:
        contract = self._contract(symbol)
        await self._ib.qualifyContractsAsync(contract)
        t = (await self._ib.reqTickersAsync(contract))[0]
        bid = float(t.bid or 0); ask = float(t.ask or 0)
        return Quote(symbol=symbol, ts=self._now(), bid=bid, ask=ask,
                     bid_size=int(t.bidSize or 0), ask_size=int(t.askSize or 0))

    # ── orders ───────────────────────────────────────────────────────
    async def place_order(self, order: Order) -> OrderAck:
        """Entry (MKT/LMT) + optional server-side OCA bracket (TP limit + SL stop)."""
        try:
            contract = self._contract(order.symbol)
            await self._ib.qualifyContractsAsync(contract)
            action = "BUY" if order.side in ("buy", "buy_to_cover") else "SELL"
            qty = order.quantity
            entry = (LimitOrder(action, qty, order.limit_price)
                     if order.order_type == "limit" and order.limit_price is not None
                     else MarketOrder(action, qty))
            has_bracket = order.stop_loss_price is not None or order.take_profit_price is not None
            entry.transmit = not has_bracket
            trade = self._ib.placeOrder(contract, entry)
            if has_bracket:
                opp = "SELL" if action == "BUY" else "BUY"
                oca = f"oca-{order.client_order_id}"
                if order.take_profit_price is not None:
                    tp = LimitOrder(opp, qty, order.take_profit_price)
                    tp.ocaGroup = oca; tp.parentId = entry.orderId; tp.transmit = order.stop_loss_price is None
                    self._ib.placeOrder(contract, tp)
                if order.stop_loss_price is not None:
                    sl = StopOrder(opp, qty, order.stop_loss_price)
                    sl.ocaGroup = oca; sl.parentId = entry.orderId; sl.transmit = True
                    self._ib.placeOrder(contract, sl)
            return OrderAck(client_order_id=order.client_order_id,
                            broker_order_id=str(trade.order.orderId), accepted=True, ts=self._now())
        except Exception as e:  # noqa: BLE001
            return OrderAck(client_order_id=order.client_order_id, broker_order_id=None,
                            accepted=False, ts=self._now(), reject_reason=str(e))

    async def modify_order(self, broker_order_id: str, changes: dict) -> OrderAck:
        """Modify a working order in place. IBKR modifies by re-transmitting the
        SAME Order object (same orderId) with changed fields — placeOrder on an
        existing orderId is an amend, not a new order. Supports limit_price,
        stop_price (aux), and quantity."""
        try:
            trade = next((t for t in self._ib.openTrades()
                          if str(t.order.orderId) == str(broker_order_id)), None)
            if trade is None:
                return OrderAck(client_order_id="", broker_order_id=broker_order_id,
                                accepted=False, ts=self._now(),
                                reject_reason="order not found among open trades")
            o = trade.order
            if changes.get("limit_price") is not None:
                o.lmtPrice = float(changes["limit_price"])
            if changes.get("stop_price") is not None:
                o.auxPrice = float(changes["stop_price"])
            if changes.get("quantity") is not None:
                o.totalQuantity = float(changes["quantity"])
            o.transmit = True
            self._ib.placeOrder(trade.contract, o)   # same orderId → amend
            return OrderAck(client_order_id=str(getattr(o, "orderRef", "") or ""),
                            broker_order_id=str(o.orderId), accepted=True, ts=self._now())
        except Exception as e:  # noqa: BLE001
            return OrderAck(client_order_id="", broker_order_id=broker_order_id,
                            accepted=False, ts=self._now(), reject_reason=str(e))

    async def cancel_order(self, broker_order_id: str) -> OrderAck:
        try:
            for t in self._ib.openTrades():
                if str(t.order.orderId) == str(broker_order_id):
                    self._ib.cancelOrder(t.order)
                    break
            return OrderAck(client_order_id="", broker_order_id=broker_order_id, accepted=True, ts=self._now())
        except Exception as e:  # noqa: BLE001
            return OrderAck(client_order_id="", broker_order_id=broker_order_id,
                            accepted=False, ts=self._now(), reject_reason=str(e))

    async def cancel_all_orders(self) -> list[OrderAck]:
        acks: list[OrderAck] = []
        try:
            self._ib.reqGlobalCancel()
            acks.append(OrderAck(client_order_id="", broker_order_id="ALL", accepted=True, ts=self._now()))
        except Exception as e:  # noqa: BLE001
            acks.append(OrderAck(client_order_id="", broker_order_id="ALL",
                                 accepted=False, ts=self._now(), reject_reason=str(e)))
        return acks

    # ── fills ────────────────────────────────────────────────────────
    async def get_fills(self, since_ts: str | None = None) -> list[Fill]:
        out: list[Fill] = []
        try:
            for fobj in await self._ib.reqExecutionsAsync():
                ex = fobj.execution; cc = fobj.contract
                out.append(Fill(
                    fill_id=ex.execId, broker_order_id=str(ex.orderId), client_order_id="",
                    symbol=cc.symbol + (cc.currency if cc.secType == "CASH" else ""),
                    ts=ex.time.isoformat() if hasattr(ex.time, "isoformat") else str(ex.time),
                    side="buy" if ex.side.upper().startswith("B") else "sell",
                    price=float(ex.price or 0), shares=int(ex.shares or 0),
                ))
        except Exception as e:  # noqa: BLE001
            logger.debug("IBKR get_fills failed: %s", e)
        return out
