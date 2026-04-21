# Phase 3 Build Prompt — Broker Layer
# Paste this entire prompt into VS Code Claude to begin Phase 3.
# Read CLAUDE.md before writing any code. All rules apply.

---

## What Phase 3 delivers

The broker abstraction layer: the `BrokerAdapter` ABC, the
`HistoricalAdapter` (research mode), the `TradeStationAdapter`
(sim + live), a stub `WebullAdapter`, the `/broker` router with
live connection status, and the emergency HALT endpoint.

After Phase 3 the topbar broker dot goes green, the /broker page
works, and the app can connect to TradeStation sim and pull real
account state. No agent code yet — that is Phase 4.

---

## Files to build (in order)

### Step 1 — brokers/__init__.py
Empty init. Create the `brokers/` directory at project root.

### Step 2 — brokers/base.py
Abstract base class all adapters implement.

```python
"""BrokerAdapter — the seam between executioner and any broker.

CLAUDE.md rule: executioner.py calls ONLY these methods. It never
imports a concrete adapter directly. Mode determines which adapter
is injected at startup.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from models.account import AccountState, Fill, Order, OrderAck, Quote


class BrokerAdapter(ABC):
    """Interface every broker adapter must implement."""

    # ── Connection ──────────────────────────────────────────────────
    @abstractmethod
    async def connect(self) -> bool:
        """Open connection / authenticate. Returns True on success."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully close connection."""

    @property
    @abstractmethod
    def connected(self) -> bool:
        """True if connection is live and authenticated."""

    @property
    @abstractmethod
    def broker_name(self) -> str:
        """Human-readable name. e.g. 'tradestation_sim'"""

    # ── Account ─────────────────────────────────────────────────────
    @abstractmethod
    async def get_account_state(self) -> AccountState:
        """Return current account snapshot."""

    # ── Market data ─────────────────────────────────────────────────
    @abstractmethod
    async def get_quote(self, symbol: str) -> Quote:
        """Return current NBBO quote for symbol."""

    # ── Orders ──────────────────────────────────────────────────────
    @abstractmethod
    async def place_order(self, order: Order) -> OrderAck:
        """Submit an order. Returns ack (accepted or rejected)."""

    @abstractmethod
    async def modify_order(self, broker_order_id: str,
                           changes: dict) -> OrderAck:
        """Modify a live order."""

    @abstractmethod
    async def cancel_order(self, broker_order_id: str) -> OrderAck:
        """Cancel a live order."""

    @abstractmethod
    async def cancel_all_orders(self) -> list[OrderAck]:
        """Cancel every open order. Used by HALT."""

    # ── Fills ───────────────────────────────────────────────────────
    @abstractmethod
    async def get_fills(self, since_ts: str | None = None) -> list[Fill]:
        """Return fills since `since_ts` (ISO8601). None = today."""
```

### Step 3 — brokers/historical.py
Research mode adapter. Reads cached OHLCV data.
No real broker connection — all methods return plausible
stub responses so research-mode agent code runs without error.

```python
"""HistoricalAdapter — research mode only.

Returns stub account state and stub quotes. Orders are simulated
(accepted immediately, no real fill). Fills are synthetic.
In Phase 4 this will read from local OHLCV cache files.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from uuid import uuid4

from brokers.base import BrokerAdapter
from models.account import AccountState, Fill, Order, OrderAck, Position, Quote

logger = logging.getLogger(__name__)

STUB_EQUITY = 162_480.00


class HistoricalAdapter(BrokerAdapter):
    """Fake broker for research / backtesting."""

    def __init__(self) -> None:
        self._connected = False

    async def connect(self) -> bool:
        self._connected = True
        logger.info("HistoricalAdapter: connected (research mode)")
        return True

    async def disconnect(self) -> None:
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def broker_name(self) -> str:
        return "historical_research"

    async def get_account_state(self) -> AccountState:
        return AccountState(
            account_id="RESEARCH-001",
            broker=self.broker_name,
            type="cash",
            equity=STUB_EQUITY,
            cash=STUB_EQUITY,
            buying_power=STUB_EQUITY,
            realized_pnl_today=0.0,
            unrealized_pnl_today=0.0,
            trades_today=0,
            day_trade_count_rolling_5d=0,
            trading_halted=False,
            ts_snapshot=datetime.now(timezone.utc).isoformat(),
        )

    async def get_quote(self, symbol: str) -> Quote:
        # Stub — Phase 4 will read from OHLCV cache
        return Quote(
            symbol=symbol,
            ts=datetime.now(timezone.utc).isoformat(),
            bid=100.00, ask=100.05,
            bid_size=500, ask_size=500,
        )

    async def place_order(self, order: Order) -> OrderAck:
        ack_id = str(uuid4())
        logger.info("HistoricalAdapter: simulated order %s %s %s",
                    order.side, order.quantity, order.symbol)
        return OrderAck(
            client_order_id=order.client_order_id,
            broker_order_id=ack_id,
            accepted=True,
            ts=datetime.now(timezone.utc).isoformat(),
        )

    async def modify_order(self, broker_order_id: str,
                           changes: dict) -> OrderAck:
        return OrderAck(
            client_order_id="", broker_order_id=broker_order_id,
            accepted=True, ts=datetime.now(timezone.utc).isoformat(),
        )

    async def cancel_order(self, broker_order_id: str) -> OrderAck:
        return OrderAck(
            client_order_id="", broker_order_id=broker_order_id,
            accepted=True, ts=datetime.now(timezone.utc).isoformat(),
        )

    async def cancel_all_orders(self) -> list[OrderAck]:
        return []

    async def get_fills(self, since_ts: str | None = None) -> list[Fill]:
        return []
```

### Step 4 — brokers/tradestation.py
The real adapter. OAuth2 + REST API.
TradeStation API base URLs:
  - Auth:  https://signin.tradestation.com/oauth/token
  - API:   https://api.tradestation.com/v3

Environment variables (from .env — never hardcoded):
  TS_CLIENT_ID, TS_CLIENT_SECRET, TS_REFRESH_TOKEN, TS_ACCOUNT_ID
  TS_SIM (= "true" for sim, "false" for live)

TradeStation uses OAuth2 with refresh tokens. The adapter:
1. Reads refresh token from .env on connect()
2. POSTs to token endpoint to get access_token + new refresh_token
3. Writes new refresh_token back to .env (token rotation)
4. Re-authenticates automatically before token expiry
5. All API calls use Bearer auth header

Build the full adapter with these methods implemented:
- connect() — OAuth token exchange
- disconnect() — clear token
- connected — property, True if token is valid and not expired
- broker_name — "tradestation_sim" or "tradestation_live"
- get_account_state() — GET /accounts/{TS_ACCOUNT_ID}/balances
  and GET /accounts/{TS_ACCOUNT_ID}/positions
  Map to AccountState model
- get_quote(symbol) — GET /marketdata/quotes/{symbol}
  Map bid/ask/sizes to Quote model
- place_order(order) — POST /accounts/{TS_ACCOUNT_ID}/orders
  Map Order model to TS order payload
- modify_order() — PUT /accounts/{TS_ACCOUNT_ID}/orders/{id}
- cancel_order() — DELETE /accounts/{TS_ACCOUNT_ID}/orders/{id}
- cancel_all_orders() — GET open orders then cancel each
- get_fills() — GET /accounts/{TS_ACCOUNT_ID}/orders
  filter by status = "FLL" (filled), map to Fill model

TradeStation order payload mapping:
  Order.side "buy"          → "BUY"
  Order.side "sell"         → "SELL"
  Order.side "buy_to_cover" → "BUY_TO_COVER"
  Order.side "sell_short"   → "SELL_SHORT"
  Order.order_type "market" → "Market"
  Order.order_type "limit"  → "Limit"
  Order.order_type "stop"   → "StopMarket"
  Order.order_type "stop_limit" → "StopLimit"
  Order.time_in_force "day" → "DAY"
  Order.time_in_force "gtc" → "GTC"

Use httpx.AsyncClient with a 10s timeout. All HTTP errors raise
a custom BrokerConnectionError (define in brokers/base.py).
Log every API call at DEBUG level with method + URL.
Log every error at ERROR level with status code + response body.

Token refresh: TradeStation access tokens expire in 20 minutes.
Track expiry with `self._token_expires_at`. Before any API call,
check if token expires within 2 minutes — if so, refresh first.

```python
# Structure outline — implement all methods fully:
class TradeStationAdapter(BrokerAdapter):
    def __init__(self, sim: bool = True) -> None:
        self._sim = sim
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0  # Unix timestamp
        self._client: httpx.AsyncClient | None = None

    # ... implement all abstract methods
```

### Step 5 — brokers/webull.py
Stub only in v1.

```python
"""WebullAdapter — stub for v1.
Real implementation in a future phase when Webull API access is set up.
"""
from brokers.base import BrokerAdapter
from models.account import AccountState, Fill, Order, OrderAck, Quote

class WebullAdapter(BrokerAdapter):
    """Not implemented in v1. Raises NotImplementedError on all calls."""

    async def connect(self) -> bool:
        raise NotImplementedError("WebullAdapter not implemented in v1")

    @property
    def connected(self) -> bool:
        return False

    @property
    def broker_name(self) -> str:
        return "webull_stub"

    # ... all other abstract methods also raise NotImplementedError
```

### Step 6 — services/broker_service.py
Singleton broker adapter instance + factory.

```python
"""broker_service.py — adapter factory and singleton access.

The active adapter is selected at startup based on settings.app.mode
and the TS_SIM environment variable. All other code that needs broker
access calls get_adapter() — never instantiates adapters directly.
"""
from __future__ import annotations
import os
import logging
from brokers.base import BrokerAdapter
from brokers.historical import HistoricalAdapter
from brokers.tradestation import TradeStationAdapter
from services.settings_service import get_settings

logger = logging.getLogger(__name__)

_adapter: BrokerAdapter | None = None


def build_adapter() -> BrokerAdapter:
    s = get_settings()
    mode = s.app.mode
    if mode == "research":
        logger.info("Broker: using HistoricalAdapter (research mode)")
        return HistoricalAdapter()
    ts_sim = os.getenv("TS_SIM", "true").lower() == "true"
    label = "sim" if ts_sim else "live"
    logger.info("Broker: using TradeStationAdapter (%s)", label)
    return TradeStationAdapter(sim=ts_sim)


def get_adapter() -> BrokerAdapter:
    global _adapter
    if _adapter is None:
        _adapter = build_adapter()
    return _adapter


async def connect_adapter() -> bool:
    adapter = get_adapter()
    if adapter.connected:
        return True
    return await adapter.connect()


def reset_adapter() -> None:
    """Force re-creation of the adapter (e.g. after mode change)."""
    global _adapter
    _adapter = None
```

Wire `connect_adapter()` into the FastAPI lifespan in `app.py`:
After `ensure_directories()`, call `await connect_adapter()`.
Log success or failure but do not crash startup on broker failure —
the app must remain usable for settings changes even if broker is down.

Update the lifespan in `app.py`:
```python
@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_directories()
    s = get_settings()
    logger.info("TradeAgent starting | mode=%s", s.app.mode)
    try:
        ok = await connect_adapter()
        logger.info("Broker adapter: %s", "connected" if ok else "failed")
    except Exception as exc:
        logger.error("Broker adapter failed to connect: %s", exc)
    yield
    adapter = get_adapter()
    if adapter.connected:
        await adapter.disconnect()
    logger.info("TradeAgent shutting down")
```

### Step 7 — routers/broker.py (replace stub)
Remove the stub route from `stubs.py` and build the real router.

Routes:
```
GET  /broker              → broker.html (full page)
GET  /api/broker/status   → JSON: connection status + account snapshot
POST /broker/halt         → cancel all orders + set trading_halted flag
POST /api/broker/connect  → trigger adapter.connect()
POST /api/broker/disconnect → trigger adapter.disconnect()
```

GET /api/broker/status response shape:
```json
{
  "connected": true,
  "broker_name": "tradestation_sim",
  "mode": "paper",
  "account": {
    "equity": 162480.00,
    "buying_power": 48220.00,
    "open_positions": 3,
    "realized_pnl_today": 847.50,
    "trading_halted": false
  },
  "ts": "iso8601"
}
```
Returns 200 with `connected: false` and null account if adapter
is not connected — never 500 on connection failure.

POST /broker/halt:
1. Call adapter.cancel_all_orders()
2. Set a module-level `TRADING_HALTED` flag in broker_service.py
3. Return 200 with {"halted": true, "cancelled_orders": N}
The HALT flag is checked by executioner in Phase 5.

### Step 8 — templates/broker.html
Replace the placeholder template.

Layout: single column, max-width 800px.

Section 1 — Connection status card:
- Large status indicator: green dot "Connected" or red "Disconnected"
- Broker name badge (tradestation_sim / tradestation_live / historical)
- Mode badge (from settings)
- [Connect] button → POST /api/broker/connect (HTMX, swap status)
- [Disconnect] button → POST /api/broker/disconnect (HTMX)
- Last connected timestamp

Section 2 — Account snapshot card (hx-get /api/broker/status,
hx-trigger="load, every 30s"):
- Equity, buying power, open positions, today's P&L
- trading_halted warning banner (amber) if flag is true
- Show "Not connected" state if disconnected

Section 3 — TradeStation configuration (display only, not editable here):
- Account ID: masked (show last 4 chars only, e.g. "****4821")
- Endpoint: Sim or Live (from TS_SIM env var)
- Note: "Credentials are stored in .env — edit directly to change"

Section 4 — Emergency controls:
- HALT button (large, red, prominent)
  Clicking shows a confirmation modal (use CSS + JS, not
  position:fixed — use a flow-positioned overlay div with
  min-height so it contributes to layout height)
  On confirm: POST /broker/halt
  On success: show "HALT executed — N orders cancelled" status
- Note below: "HALT cancels all open orders and prevents new
  executions. To resume, restart the app or toggle mode in Settings."

Section 5 — Connection log (last 10 events):
- Simple list: timestamp + event (connected, disconnected, auth
  refreshed, HALT fired)
- Stubbed in Phase 3 with hardcoded events; real log in Phase 6

### Step 9 — Topbar status dots (update base.html)

Wire the topbar broker dot to the /api/broker/status endpoint.
Add HTMX polling to the topbar broker status element:

```html
<div class="topbar-status"
     hx-get="/api/broker/status"
     hx-trigger="load, every 30s"
     hx-target="this"
     hx-swap="outerHTML">
  <span class="dot gray"></span><span>Broker</span>
</div>
```

Create a partial template `templates/broker/_status_dot.html`:
```html
<div class="topbar-status"
     hx-get="/api/broker/status"
     hx-trigger="every 30s"
     hx-target="this"
     hx-swap="outerHTML">
  {% if status.connected %}
    <span class="dot green"></span><span>{{ status.broker_name }}</span>
  {% else %}
    <span class="dot red"></span><span>Broker offline</span>
  {% endif %}
</div>
```

The /api/broker/status route needs an HTMX-aware response:
- If HX-Request header present: return broker/_status_dot.html partial
- Otherwise: return full JSON (for the broker page)
Use `request.headers.get("HX-Request")` to detect.

---

## Environment variables (.env)

Create a `.env.example` file (commit this) and a `.env` file
(gitignored, already in .gitignore from Phase 1):

```
# .env.example — copy to .env and fill in real values
# NEVER commit .env

TS_CLIENT_ID=your_client_id_here
TS_CLIENT_SECRET=your_client_secret_here
TS_REFRESH_TOKEN=your_refresh_token_here
TS_ACCOUNT_ID=your_account_id_here
TS_SIM=true
```

Load in app.py using python-dotenv (already in requirements.txt):
```python
from dotenv import load_dotenv
load_dotenv()  # call before any os.getenv()
```

---

## TradeStation OAuth setup instructions

Add this to broker.html as a collapsible "Setup guide" section.
This is for the user to follow once, not for the app to automate.

```
TradeStation API Setup (one-time):

1. Go to https://developer.tradestation.com
2. Create an app — note Client ID and Client Secret
3. Set redirect URI to http://localhost:5000/oauth/callback
4. To get your initial refresh token, visit:
   https://signin.tradestation.com/oauth/authorize
   ?response_type=code
   &client_id=YOUR_CLIENT_ID
   &redirect_uri=http://localhost:5000/oauth/callback
   &audience=https://api.tradestation.com
   &scope=openid profile MarketData ReadAccount Trade
5. After login, copy the `code` from the redirect URL
6. POST to https://signin.tradestation.com/oauth/token with:
   grant_type=authorization_code, code=..., client_id=...,
   client_secret=..., redirect_uri=...
7. Save the refresh_token from the response to your .env file
8. The app auto-rotates the refresh token on each startup
```

---

## Verification checklist (run after Phase 3 is complete)

- [ ] `brokers/` directory exists with base.py, historical.py,
      tradestation.py, webull.py, __init__.py
- [ ] `services/broker_service.py` exists
- [ ] App starts without error in research mode (no .env needed)
- [ ] GET /health returns 200
- [ ] GET /broker/status returns JSON with connected field
- [ ] Topbar broker dot changes color based on connection state
- [ ] POST /broker/halt returns {"halted": true}
- [ ] HALT button on /broker page shows confirmation dialog
  (not position:fixed modal — flow-positioned overlay)
- [ ] TradeStation adapter handles missing .env gracefully:
  logs error, returns connected=false, does not crash app
- [ ] HistoricalAdapter connects successfully in research mode
- [ ] .env.example committed; .env in .gitignore
- [ ] No broker credentials hardcoded anywhere in source files
- [ ] All new files have module-level docstrings
- [ ] All methods have type hints on parameters and return values

---

## CLAUDE.md updates to make after Phase 3

After Phase 3 passes verification, update CLAUDE.md:

Add to the project structure under brokers/:
```
├── brokers/
│   ├── __init__.py
│   ├── base.py              ← BrokerAdapter ABC + BrokerConnectionError
│   ├── tradestation.py      ← OAuth2 + REST; reads TS_* env vars
│   ├── historical.py        ← Research mode stub
│   └── webull.py            ← v1 stub (NotImplementedError)
```

Add to services/:
```
│   ├── broker_service.py    ← Singleton adapter factory; get_adapter()
```

Add this rule to the "What Claude should NOT do" section:
- Do not instantiate BrokerAdapter subclasses anywhere except
  broker_service.py. All broker access goes through get_adapter().
- Do not store TS_REFRESH_TOKEN anywhere except .env. The adapter
  reads and writes it there directly.
- Do not use position:fixed in any template (iframe viewport issue).
  Use flow-positioned overlays with min-height for modals.

Note the SQLite path decision (to be added if not already present):
- SQLite lives at C:/Temp/claude_trading_app.db — NOT on Drive.
  Drive sync + SQLite fsync = corruption risk. This is a hard rule.
```
