# Broker Integration — FX & Futures options

How to add FX and futures execution to TradeAgent. The app already has a clean broker
seam: every adapter implements `brokers/base.py::BrokerAdapter` and is selected in
`services/broker_service.py` by `provider` (registry row) or `BROKER_PROVIDER` (env).
Adding a venue = one adapter file + one routing branch. Current adapters: alpaca
(US stocks, default), tradestation (stocks/futures, opt-in), historical (research),
**ibkr (FX+futures+stocks — CHOSEN, skeleton added)**, oanda (FX — alternative skeleton).

## ✅ DECISION: Interactive Brokers (IBKR)
You have an IBKR account, so IBKR is the path — one API for FX + futures + stocks + options.
Key difference vs a cloud REST broker: **IBKR's API talks to a LOCAL gateway you run**, not a
web endpoint.

Quickstart (paper first):
1. Install/run **IB Gateway** (headless, recommended for automation) or **TWS**.
2. In its settings: **Configure → API → Enable ActiveX and Socket Clients** = ON;
   add `127.0.0.1` to trusted IPs.
3. Ports: IB Gateway **paper 4002** / live 4001 ; TWS **paper 7497** / live 7496.
4. `pip install ib_insync` (or the maintained fork `ib_async`).
5. In `.env`: `IBKR_HOST=127.0.0.1`, `IBKR_PORT=4002`, `IBKR_CLIENT_ID=7`, `BROKER_PROVIDER=ibkr`.
6. Smoke (paper port) before anything live: `connect()` → `get_account_state()` → `get_quote("EURUSD")`
   → one tiny market order → confirm fill → `cancel_all_orders()`.
7. Automation note: IBKR forces a periodic re-auth; for unattended running use **IBC (IBController)**
   to auto-restart/login IB Gateway.

`brokers/ibkr.py` (skeleton, via ib_insync): connect, account summary + positions, quote,
market/limit entry with an OCA take-profit + stop-loss bracket, cancel, global-cancel, fills.
Asset routing: 6-letter alpha → Forex(IDEALPRO); `SYM=FUT:EXCH:YYYYMM` → Future; else Stock(SMART).
**Untested against a live gateway — verify on the paper port first.**

## FX brokers with a usable API

| Broker | API | Practice/demo | Cost | Fit |
|---|---|---|---|---|
| **OANDA** (recommended) | v20 REST + streaming | ✅ free practice acct | no API fee; spread/commission only | **Best for us** — clean REST, Python lib (oandapyV20), covers FX + metals (XAU). Matches our HistData FX + the FVG strategy. |
| FOREX.com / GAIN | REST API | demo | spread | Solid alternative; heavier onboarding. |
| cTrader Open API (Pepperstone, IC Markets…) | FIX/Open API | demo | spread | Good fills, but FIX/OAuth complexity. |
| Saxo | OpenAPI | sim | tiered | Multi-asset incl. FX + futures; enterprise-ish. |
| Interactive Brokers | TWS/Client Portal API | ✅ paper | low | Multi-asset (FX too) but heavier (gateway). See below. |

**Recommendation: OANDA.** Free practice account, no API fee, simplest REST, and it's
the venue our validated FVG-continuation strategy is built for. The adapter skeleton is
already in `brokers/oanda.py`. To go live on practice: open a free OANDA practice
account → generate a token → fill `OANDA_*` in `.env` (see `.env.example`) → set
`BROKER_PROVIDER=oanda` (or add an 'oanda' account on `/broker`).

## Futures brokers with a usable API

| Broker | API | Paper | Notes | Fit |
|---|---|---|---|---|
| **Interactive Brokers** | TWS API / Client Portal / ib_insync | ✅ paper | Broadest: futures + FX + stocks + options in ONE API. Requires a running Gateway/TWS. | Best if we want **one adapter for everything**. Most powerful, most setup. |
| **TradeStation** (already stubbed) | REST v3 | ✅ sim | Commission-free futures; already partially integrated in the app. | Fastest futures path for us — extend the existing adapter. |
| **Tradovate** | REST/WebSocket | ✅ demo | Cloud, flat-rate plans, low intraday margins; popular with day traders. | Clean futures-only API. |
| NinjaTrader | API | ✅ sim | Low futures fees/margins; strong platform. | Alternative. |

**Recommendation for futures:** extend the **TradeStation** adapter we already have
(fastest, commission-free futures, sim account), or add **Interactive Brokers** if we
want a single adapter spanning FX + futures + stocks. Tradovate is the cleanest
futures-only option if TS proves awkward.

## What's built now (this session)
- `brokers/oanda.py` — OANDA v20 FX adapter **skeleton** against the BrokerAdapter seam:
  connect, account summary, quote, market/limit order with server-side SL/TP bracket,
  cancel, cancel-all, fills. Symbol mapping (EURUSD↔EUR_USD), units sign by side.
  **Untested against a live account** — smoke `connect()` + `get_account_state()` on a
  **practice** account first; only then exercise `place_order()`.
- `services/broker_service.py` — routes `provider == "oanda"` (registry) and
  `BROKER_PROVIDER=oanda` (env) to `OandaAdapter`.
- `.env.example` — `OANDA_API_TOKEN / OANDA_ACCOUNT_ID / OANDA_ENV` + `BROKER_PROVIDER`.

## Remaining work to actually trade FX live
1. **Verify the OANDA adapter** on a practice account (connect → account → quote →
   tiny market order → fill → cancel). Fix any field mappings.
2. **Instrument/units model:** the app's Order/Position use integer "shares"; FX uses
   "units" (works as-is) but position sizing, pip value, and risk math need an FX-aware
   path in `portfolio_manager` (currently %-equity / share-based).
3. **Intraday workflow + scheduler:** the FVG-continuation fires intraday (NY session),
   unlike the daily post-close scans. Needs an intraday detector + an intraday workflow
   (model the existing `double_lock` 10:30 ET job).
4. **/broker UI:** add an "oanda" provider option in the account form (token + account id).
5. **Gates:** compliance/risk gates assume equities (PDT, wash-sale, SSR). Add an
   FX path that skips the inapplicable ones.

Until 1–5 are done, trade the strategy **manually** — see FVG_MANUAL_PLAYBOOK.md.
