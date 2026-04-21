# TradeAgent — Project Context for Claude Code
**Last synced:** 2026-04-20
**Status:** Phases 1–3 complete 2026-04-18. Phase 4 (Agents + Workflow Engine) next.
**Roadmap revised 2026-04-20:** Phase 5 is now Backtest Engine (was Approval
Flow). Approval Flow + Executioner moved to Phase 6. Scheduler + Memory +
Mobile polish moved to Phase 7. This reorder exists so strategies are
validated over 10+ years of bars before the live executioner is wired up.
**Companion docs:**
  - `_AgenticSkills/trading_architect_skill/SKILL.md` (Google Drive) — domain logic
  - `phase2_prompt.md` (project root) — UI design system + per-screen layouts (still authoritative for any UI work)
  - `phase4_prompt.md` (project root) — Phase 4 agents + workflow engine spec (revised 2026-04-20)
**Stack:** FastAPI · HTMX 2.0.4 · Jinja2 · hand-rolled CSS (dark theme) · SQLite · JSONL · Tailscale · ntfy · TradeStation API
**Python:** 3.14.4 (moved off 3.12 on 2026-04-20 — the 3.12 install went missing and 3.14 wheels
resolved cleanly for pandas 3.0, numpy 2.4, alpaca-py 0.43, yfinance 1.3; no compat issues)
**Location:** `C:\Projects\TradingApp\` (local). Moved off Google Drive 2026-04-20 — Drive
sync + venv/SQLite was creating constant fsync churn. Cross-machine story: git clone for
code, `scripts/backup_trade_logs.ps1` for the ML data pool, one-time copy for `.env` secrets.

---

## What this application is

A multi-agent trading workflow manager for US equities and ETFs. It coordinates autonomous
agents that screen stocks, generate trade signals, plan trades, enforce compliance and risk
rules, and route approved plans to a broker for execution. It is NOT a generic web app —
every architectural decision is driven by the trading domain logic in SKILL.md.

The app has two distinct roles:
1. **Orchestrator** — runs and coordinates the Python trading agents
2. **Control surface** — dashboard, approval queue, configuration UI for the human operator

---

## Non-negotiables (read before writing any code)

- **Mode is the master switch.** Every route, agent call, and broker interaction must
  respect `settings.mode` ∈ {research, paper, live}. Research = no broker, historical
  data only. Paper = full gates, sim broker. Live = full gates, live broker, human ack
  required before any order reaches the broker.

- **Two hard gates that cannot be bypassed by any code path:**
  - `compliance_officer` — runs before risk. Blocks on wash sale, PDT, halt, SSR,
    earnings blackout, restricted list, incomplete plan.
  - `risk_manager` — runs after compliance. Can approve, resize, or reject.
  - If either gate returns a non-pass verdict, execution stops. No exceptions.
  - These are Python classes, not just API checks — they run in-process.

- **Human ack is mandatory in live mode.** No order reaches `executioner.execute()`
  without a `human_ack_record` with `action == "approve"` and `ts` within 15 minutes.
  This is enforced in `executioner.py`, not in the UI — the UI cannot bypass it.

- **Every completed trade writes a `trade_record` to JSONL.** This is the ML data pool.
  Missing or partial records are a product defect, not a minor omission.

- **Broker adapter is a seam.** `executioner` calls `BrokerAdapter` interface methods only.
  It never imports `tradestation_adapter` or `webull_adapter` directly — only the
  interface. Mode determines which adapter is injected at startup.

---

## Project structure (target — build toward this)

```
trading_app/
├── CLAUDE.md                    ← you are here
├── .env                         ← broker credentials, never committed
├── .gitignore
├── requirements.txt
├── app.py                       ← FastAPI entrypoint; mounts routers
│
├── agents/
│   ├── __init__.py
│   ├── universe_filter.py       ← Finviz screener → universe_result
│   ├── analyst.py               ← 4 lenses → signal objects
│   ├── portfolio_manager.py     ← signals → trade_plan
│   ├── compliance_officer.py    ← trade_plan → compliance_verdict (GATE)
│   ├── risk_manager.py          ← trade_plan → risk_verdict (GATE) + postmortem
│   └── executioner.py           ← approved plan → broker_adapter calls
│
├── brokers/                     ← Built in Phase 3 (spec-aligned 2026-04-18)
│   ├── __init__.py
│   ├── base.py                  ← BrokerAdapter ABC + BrokerConnectionError.
│   │                              `connected` and `broker_name` are sync
│   │                              `@property`; everything else async.
│   ├── historical.py            ← Research adapter. Stub account ($162,480),
│   │                              stub quote ($100.00/$100.05), simulated
│   │                              orders (instant accept, no real fill).
│   │                              Phase 4 will read OHLCV from
│   │                              data/historical/ (already populated by
│   │                              scripts/download_history.py).
│   ├── tradestation.py          ← Paper+live adapter. OAuth refresh-token
│   │                              model: user does authorize dance ONCE
│   │                              offline (see /broker setup guide), drops
│   │                              TS_REFRESH_TOKEN into .env, app rotates
│   │                              the refresh token back into .env on each
│   │                              connect. Real REST methods implemented
│   │                              (balances, positions, quotes, orders,
│   │                              cancel-all, fills). 2-min refresh margin.
│   └── webull.py                ← v1 stub: every method NotImplementedError.
│
├── scripts/
│   ├── __init__.py
│   └── download_history.py      ← yfinance bulk-downloader CLI
│                                  `python -m scripts.download_history SPY AAPL --years 20`
│
├── models/
│   ├── __init__.py
│   ├── signal.py                ← Pydantic: Signal
│   ├── trade_plan.py            ← Pydantic: TradePlan (the central object)
│   ├── verdicts.py              ← Pydantic: ComplianceVerdict, RiskVerdict
│   ├── trade_record.py          ← Pydantic: TradeRecord (JSONL schema)
│   └── account.py               ← Pydantic: AccountState, Quote, Fill
│
├── routers/                     ← All built in Phase 2 except those marked
│   ├── __init__.py
│   ├── dashboard.py             ← GET /, /api/dashboard/{stats,agents,activity}
│   ├── pending.py               ← GET /pending, /pending/{id}; POST /pending/{id}/ack;
│   │                              GET /api/pending/count (sidebar badge)
│   ├── trades.py                ← GET /trades, /trades/analysis (placeholder),
│   │                              GET /api/trades (filters)
│   ├── settings.py              ← GET/POST /settings; POST /api/ntfy/test (stub)
│   ├── broker.py                ← Phase 3: GET /broker (page),
│   │                              GET /api/broker/status (HX-Request →
│   │                              topbar dot partial; otherwise JSON),
│   │                              GET /api/broker/account-card (HTML
│   │                              partial for the snapshot card),
│   │                              POST /api/broker/connect | disconnect,
│   │                              POST /broker/halt → cancels all + sets
│   │                              TRADING_HALTED flag, returns
│   │                              {"halted": true, "cancelled_orders": N}.
│   ├── stubs.py                 ← Placeholders for /universe, /strategies,
│   │                              /console (real ones later)
│   └── universe.py              ← Phase 4: Finviz screener
│
├── services/
│   ├── __init__.py
│   ├── settings_service.py      ← Load/save settings.yaml + path constants
│   ├── log_service.py           ← Append/read JSONL trade logs (async)
│   ├── stub_data.py             ← Phase 2 stub UI data (replaced in Phase 4–5)
│   ├── broker_service.py        ← Phase 3: adapter factory + FastAPI dep.
│   │                              `get_broker()` returns the right adapter
│   │                              for the current mode; `reset_broker()`
│   │                              tears down after mode change or OAuth reset.
│   ├── memory_service.py        ← Phase 6: SQLite similarity queries
│   ├── ntfy_service.py          ← Phase 5: push notifications
│   └── scheduler.py             ← Phase 6: APScheduler pre-market jobs
│
├── templates/                   ← Subdirs hold HTMX partials per page
│   ├── base.html                ← Shell: sidebar (9 items + SVG icons), topbar
│   │                              (mode badge, ET clock, HALT, broker/Tailscale dots)
│   ├── _placeholder.html        ← Generic "Coming in Phase X" page
│   ├── dashboard.html
│   ├── dashboard/
│   │   ├── _stats.html          ← 4 stat cards (HTMX partial)
│   │   ├── _agents.html         ← 6 agent status rows (HTMX partial)
│   │   └── _activity.html       ← Today's activity log (HTMX partial, 60s refresh)
│   ├── pending.html             ← Split layout (340px queue + detail w/ TradingView)
│   ├── trades.html
│   ├── trades/
│   │   ├── _table.html          ← Filterable trade table (HTMX partial)
│   │   └── analysis.html        ← Phase 6 placeholder
│   ├── settings.html
│   ├── settings/
│   │   └── _save_status.html    ← Save toast (HTMX partial)
│   └── broker.html              ← Phase 3: connection + OAuth + halt
│
├── static/                      ← Currently empty; HTMX & Tailwind via CDN.
│                                  Localize (htmx.min.js, app.css) when offline use needed.
│
└── data/                        ← gitignored (all subdirs regenerable)
    ├── logs/                    ← Agent decision logs (verbose)
    ├── historical/              ← yfinance bar CSVs (Phase 4+)
    ├── news_cache/              ← Alpaca news per (symbol, date) (Phase 4+)
    ├── edgar_cache/             ← SEC filings per symbol (Phase 4+)
    ├── sentiment_cache/         ← AV sentiment (optional) (Phase 4+)
    └── claude_trading_app.db    ← SQLite; auto-created on app startup,
                                   rebuilt from trade_logs on startup
```

---

## Core data objects (Pydantic models — build these first)

These are the contracts between every component. Get them right before writing any agent
or route logic. All are defined in `models/`.

### TradePlan (the central object)
```python
class EntryOrder(BaseModel):
    type: Literal["limit", "stop", "market_on_trigger"]
    price: float
    trigger_condition: str | None = None
    valid_until: str  # "session_close" | "gtc" | iso8601

class TakeProfitLeg(BaseModel):
    leg: int
    price: float
    size_pct: float  # must sum to 100 across all legs
    reason: str

class StopLossInitial(BaseModel):
    type: Literal["hard", "stop_limit"]
    price: float
    reason: str

class TrailingStop(BaseModel):
    active: bool
    activate_after: str  # e.g. "price >= entry + 1.0R"
    mode: Literal["atr", "percent", "structural"]
    atr_multiple: float | None = None
    atr_period: int | None = None
    percent: float | None = None

class TimeStop(BaseModel):
    active: bool
    condition: str
    deadline: str  # iso8601

class ThesisInvalidation(BaseModel):
    active: bool
    condition: str

class StopLoss(BaseModel):
    initial: StopLossInitial
    trail: TrailingStop
    time_stop: TimeStop
    thesis_invalidation: ThesisInvalidation

class Setup(BaseModel):
    direction: Literal["long", "short"]
    entry: EntryOrder
    take_profit: list[TakeProfitLeg]
    stop_loss: StopLoss

    @field_validator("take_profit")
    @classmethod
    def tp_sums_to_100(cls, v: list[TakeProfitLeg]) -> list[TakeProfitLeg]:
        total = sum(leg.size_pct for leg in v)
        if abs(total - 100.0) > 1e-6:
            raise ValueError(f"take_profit size_pct must sum to 100; got {total}")
        return v

class TradePlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    ts_created: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    mode: Literal["research", "paper", "live"]
    schema_version: str = "1.0.0"
    instrument: dict       # symbol, asset_class, exchange, sector, industry
    thesis: dict           # summary, lenses_contributing, conviction, etc.
    setup: Setup
    risk: dict             # r_per_share, position_size_shares, notional, pcts, rr ratios
    execution: dict        # algo, participation_cap, spread_max, broker, account_type
    evidence: list[dict]
    tradingview_chart_url: str
```

### TradeRecord (JSONL schema — never change field names after v1.0)
```python
class TradeRecord(BaseModel):
    trade_id: str
    plan_id: str
    schema_version: str = "1.0.0"
    mode: Literal["research", "paper", "live"]
    broker: str
    instrument: dict
    lifecycle: dict         # ts_planned, ts_approved, ts_entered, ts_exited_last, etc.
    setup_snapshot: dict    # strategy_name, filter_preset, lenses, market_context,
                            # entry_features (the ML feature vector)
    execution: dict         # planned vs actual prices, slippage, algo, exits, fees
    outcome: dict           # pnl_usd, pnl_r_multiple, mfe, mae, win, exit_reason
    postmortem: dict        # thesis_validated, learning_tags, parameter_adjustments
```

---

## Storage rules

**Everything lives inside the project root** at `C:\Projects\TradingApp\`.
Single location, no cloud sync on the project tree. The Drive carve-out
for SQLite (previously at `C:/Temp/`) was retired 2026-04-20 — the whole
project now sits on a non-synced local path, so there's no Drive watcher
to carve around. `.gitignore` splits what lives on disk into two groups:
**committed** (source + examples) vs **local-only** (venv, caches, DB,
secrets, trade logs).

| Data | Location | Format | In git? | Cross-machine? |
|---|---|---|---|---|
| Source code | `agents/`, `services/`, `routers/`, etc. | .py | ✅ commit | git clone / pull |
| Templates | `settings.example.yaml`, `.env.example` | YAML / dotenv | ✅ commit | git clone |
| Filter presets | `universe_filters/*.yaml` | YAML | ✅ commit | git clone |
| Strategy configs | `strategy_configs/*.yaml` | YAML | ✅ commit | git clone |
| Workflows | `workflows/*.yaml` (Phase 4+) | YAML | ✅ commit | git clone |
| `settings.yaml` | project root | YAML | ❌ gitignored | copy from example + hand-edit |
| `.env` | project root | dotenv | ❌ gitignored | **manual copy** (password manager) |
| Trade logs | `trade_logs/YYYY-MM.jsonl` | JSONL append-only | ❌ gitignored | **`scripts/backup_trade_logs.ps1`** — the ML data pool, preserve across machines |
| SQLite DB | `data/claude_trading_app.db` | SQLite | ❌ gitignored | **rebuilt from trade_logs on startup** — don't copy |
| Bar cache | `data/historical/*.csv` | CSV | ❌ gitignored | regenerate via `python -m scripts.download_history` |
| News cache | `data/news_cache/{SYMBOL}/*.jsonl` | JSONL | ❌ gitignored | regenerate (first run populates from Alpaca) |
| EDGAR cache | `data/edgar_cache/*.jsonl`, `edgar_cik_map.json` | JSONL / JSON | ❌ gitignored | regenerate |
| Sentiment cache | `data/sentiment_cache/*.json` | JSON | ❌ gitignored | regenerate |
| Agent logs | `data/logs/*.log` | text | ❌ gitignored | not preserved |
| venv | `.venv/` | Python | ❌ gitignored | `python -m venv .venv && pip install -r requirements.txt` |

**Backup story.** The only non-git thing that matters cross-machine is
`trade_logs/`. `scripts/backup_trade_logs.ps1` robocopies it to a
Drive-synced folder (`C:\Users\juliu\My Drive\TradeAgentBackups\`) so
your accumulated ML data survives laptop deaths and moves between
machines. Run it manually after every trading session for now;
APScheduler will pick it up in Phase 7.

**Path constants** — define once in `services/settings_service.py`:
```python
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_FILE = PROJECT_ROOT / "settings.yaml"
TRADE_LOG_DIR = PROJECT_ROOT / "trade_logs"
FILTER_PRESET_DIR = PROJECT_ROOT / "universe_filters"
STRATEGY_CONFIG_DIR = PROJECT_ROOT / "strategy_configs"
DATA_DIR = PROJECT_ROOT / "data"
LOCAL_LOGS_DIR = DATA_DIR / "logs"
ENV_FILE = PROJECT_ROOT / ".env"

# SQLite in-project (no more Drive carve-out; gitignored)
LOCAL_DB_PATH = DATA_DIR / "claude_trading_app.db"
```

**JSONL write rule:** Always open in append mode (`"a"`), write one JSON line, flush
immediately. Never rewrite the file. Never hold a file handle open between writes.

---

## API routes (FastAPI routers)

```
GET  /                             → dashboard.html
GET  /pending                      → pending.html (list)
GET  /pending/{plan_id}            → pending_detail.html (TradingView + full plan)
POST /pending/{plan_id}/ack        → process human_ack_record; trigger executioner
GET  /universe/latest              → JSON: last universe_result
POST /universe/run                 → trigger universe_filter with named preset
GET  /trades                       → trades.html (reads JSONL)
GET  /trades/analysis              → analysis.html (aggregates from JSONL)
GET  /strategies                   → strategies.html
POST /strategies/{name}/toggle     → toggle strategy active/inactive
GET  /settings                     → settings.html
POST /settings                     → update settings.yaml
GET  /broker/status                → JSON: adapter connection + account state
POST /broker/halt                  → emergency stop (cancel all, halt flag)
GET  /console                      → console.html (SSE log stream)
GET  /api/sse/logs                 → SSE stream for agent console
```

---

## TradingView chart embed (pending_detail.html)

No API key required. Use the Advanced Charts widget:
```html
<div id="tv-chart" style="height:400px"></div>
<script src="https://s3.tradingview.com/tv.js"></script>
<script>
new TradingView.widget({
  container_id: "tv-chart",
  symbol: "NASDAQ:{{ plan.instrument.symbol }}",
  interval: "60",
  theme: "light",
  style: "1",
  locale: "en",
  autosize: true,
  hide_side_toolbar: false
});
</script>
```

---

## ntfy notification payload

Fire on every new pending approval (live mode) and on critical events.
```python
# services/ntfy_service.py
import httpx

async def notify_pending_approval(plan: TradePlan, settings: Settings):
    symbol = plan.instrument["symbol"]
    direction = plan.setup.direction.upper()
    entry = plan.setup.entry.price
    risk = plan.risk["position_risk_usd"]
    conv = int(plan.thesis["conviction"] * 100)
    plan_id = plan.plan_id
    host = settings.app.tailscale_hostname
    port = settings.app.port

    await httpx.AsyncClient().post(
        f"{settings.ntfy.server}/{settings.ntfy.topic}",
        json={
            "title": f"Trade Pending: {symbol} {direction}",
            "message": f"Entry ${entry} · Risk ${risk:.0f} · Conv {conv}%",
            "priority": "high",
            "tags": ["chart_increasing"],
            "click": f"http://{host}:{port}/pending/{plan_id}"
        }
    )
```

---

## Compliance gates (implement as methods on ComplianceOfficer class)

Each gate is a method that returns `ComplianceVerdict | None` (None = pass).
Run all gates in sequence; return on first non-None verdict.

```python
class ComplianceOfficer:
    def check(self, plan: TradePlan, account: AccountState,
              market_state: MarketState) -> ComplianceVerdict:
        gates = [
            self._c1_halt_check,
            self._c2_luld_check,
            self._c3_ssr_check,
            self._c4_wash_sale_check,
            self._c5_pdt_check,
            self._c6_restricted_list_check,
            self._c7_earnings_blackout_check,
            self._c8_plan_completeness_check,
        ]
        for gate in gates:
            result = gate(plan, account, market_state)
            if result is not None:
                return result  # BLOCK
        return ComplianceVerdict(result="pass", gates_evaluated=[...])
```

---

## Risk gates (implement as methods on RiskManager class)

Each gate either passes, resizes, or rejects.
```python
class RiskManager:
    def pre_trade_check(self, plan: TradePlan,
                        account: AccountState) -> RiskVerdict:
        # R1: per-trade risk cap → resize if needed
        # R2: notional cap → resize if needed
        # R3: daily loss cap → reject if hit
        # R4: max open positions → reject
        # R5: max daily trades → reject
        # R6: sector concentration → reject
        # R7: minimum R:R → reject
        # R8: participation rate → resize
        # R9: spread → reject or defer
        ...

    def post_trade(self, plan: TradePlan, fills: list[Fill],
                   price_series: list[float]) -> TradeRecord:
        # Compute slippage, MFE, MAE, R-multiple
        # Generate postmortem dict
        # Return complete TradeRecord for JSONL write
        ...
```

---

## Build order (phases)

Build in this sequence. Do not jump ahead — each phase depends on the previous.

### Phase 1 — Foundation (no agents yet) — ✅ COMPLETE 2026-04-17
1. ✅ `requirements.txt` + `.venv` with all deps installed
2. ✅ `models/` — Signal, TradePlan (+Setup, EntryOrder, TPLeg, StopLoss, etc.),
      ComplianceVerdict, RiskVerdict, HumanAckRecord, TradeRecord, AccountState,
      Quote, Order, Fill, Position, MarketState, LULDBand. Pydantic v2 throughout.
3. ✅ `services/settings_service.py` — Settings schema, get/save/reload, path
      constants (PROJECT_ROOT, TRADE_LOG_DIR, …, LOCAL_DB_PATH under data/
      in-project; the original C:/Temp carve-out was retired 2026-04-20
      when the project moved off Drive to a local C: path),
      `ensure_directories()` bootstrap.
4. ✅ `services/log_service.py` — async JSONL append + read, monthly bucketing
      by `lifecycle.ts_exited_last`.
5. ✅ `app.py` — FastAPI app, lifespan calls `ensure_directories()`, `/health`
      endpoint, `/` renders shell.
6. ✅ `templates/base.html` — sidebar (9 nav items), topbar with mode badge
      (research=blue / paper=amber / live=red), HTMX + Tailwind via CDN.

### Phase 2 — UI shell (no agents yet) — ✅ COMPLETE 2026-04-17
Spec: see `phase2_prompt.md` (authoritative for design system + per-screen layouts).
7. ✅ `static/app.css` (15KB hand-rolled) + `static/htmx.min.js` (51KB v2.0.4 localized)
8. ✅ `templates/base.html` rewritten — dark theme, CSS-grid shell, sidebar with
      inline Lucide-style SVG icons, topbar with mode badge / broker & Tailscale
      dots / ET clock / HALT button.
9. ✅ `services/stub_data.py` — STUB_ACCOUNT/AGENTS/PENDING/TRADES/POSITIONS/ACTIVITY
      shared across templates; helpers `hold_seconds_to_human`, `time_ago`.
10. ✅ `routers/dashboard.py` + `templates/dashboard.html` (+ 3 partials).
11. ✅ `routers/settings.py` + `templates/settings.html` — **real save** to
      `settings.yaml` covering app/risk_defaults/compliance/ntfy sections.
      Fields not in form (host, priority_map, execution windows, data paths)
      are preserved as-is. POST `/api/ntfy/test` returns a stub toast (Phase 5).
12. ✅ `routers/trades.py` + `templates/trades.html` (+ `_table.html` partial,
      `analysis.html` Phase-6 placeholder). Filter bar wired (symbol, strategy,
      outcome, date range). Reads `STUB_TRADES` for now — real JSONL aggregation
      lands in Phase 5 when actual trades exist.
13. ✅ `routers/pending.py` + `templates/pending.html` — full split layout with
      TradingView iframe, trade-setup table, thesis/evidence/gate cards, sticky
      approval bar with 15-minute countdown. POST `/pending/{id}/ack` returns a
      stub toast (real HumanAckRecord flow lands in Phase 5).
14. ✅ `routers/stubs.py` + `templates/_placeholder.html` — pages for
      `/universe`, `/strategies`, `/broker`, `/console` so the sidebar nav
      doesn't 404 before those phases land.

**Phase 2 deviations from `phase2_prompt.md`:**
- Sidebar footer "current user" — Settings has no `user` field, so we show
  `settings.ntfy.topic` with the `trading-agent-` prefix stripped.
- Sidebar footer "v1.0.0" — we show actual `app.version` (currently `0.1.0`)
  so it stays truthful as we ship.
- Mode badge colors: `RESEARCH=blue`, `PAPER=amber`, `LIVE=green` (per phase2
  spec). This overrides the earlier Phase-1 choice of `LIVE=red`.
- Activity-log endpoint: `/api/dashboard/activity` (not enumerated in spec but
  needed for the 60s auto-refresh).

### Phase 3 — Broker layer — ✅ COMPLETE 2026-04-18 (spec-aligned)
Spec: see `phase3_prompt.md`. The first build deviated from spec; we
realigned 2026-04-18 to match verbatim. Notable change in the realignment:
the OAuth flow is now manual-refresh-token (user does the authorize dance
once offline, drops `TS_REFRESH_TOKEN` into `.env`) instead of an
interactive in-app flow.
10. ✅ `brokers/base.py` — `BrokerAdapter` ABC. `connected` and
      `broker_name` are sync `@property`; all other methods async. Single
      `BrokerConnectionError` exception (no broader hierarchy).
11. ✅ `brokers/historical.py` — research-mode stub. Fixed account state
      ($162,480 equity, RESEARCH-001), fixed quote ($100.00/$100.05),
      orders accepted instantly with no fill, `cancel_all_orders` returns
      `[]`. **Phase 4 will wire it to read OHLCV from `data/historical/`**
      (CSVs already produced by `scripts/download_history.py`).
12. ✅ `brokers/tradestation.py` — paper (sim) + live adapter via
      TradeStation API v3. Refresh-token model: `connect()` POSTs to the
      token endpoint with `TS_REFRESH_TOKEN`, persists the rotated refresh
      token back to `.env` (and to `os.environ`). 2-min refresh margin.
      Real REST methods: account balances + positions, quotes, place/modify/
      cancel orders, cancel-all (lists open then cancels each), fills.
13. ✅ `brokers/webull.py` — v1 stub: every method `NotImplementedError`.
14. ✅ `services/broker_service.py` — `build_adapter()` reads mode +
      `TS_SIM` env; `get_adapter()` singleton; `connect_adapter()` is the
      lifespan entry point; `reset_adapter()` for mode-change rebuilds;
      module-level `TRADING_HALTED` flag + `set_halted()` mutator.
15. ✅ `routers/broker.py` + `templates/broker.html` — full UI: connection
      card with Connect/Disconnect, account snapshot (HTMX 30s refresh),
      TradeStation config card (masked account ID), HALT with **flow-positioned**
      confirmation overlay (NOT `position:fixed` — iframe viewport rule),
      stubbed connection log, collapsible OAuth setup guide.
      Topbar broker dot polls `/api/broker/status` every 30s and goes green
      when connected.
16. ✅ `app.py` lifespan — `load_dotenv()` on import; lifespan calls
      `connect_adapter()` and logs success/failure without crashing
      startup. Disconnects on shutdown.
17. ✅ `.env.example` — documents `TS_CLIENT_ID`, `TS_CLIENT_SECRET`,
      `TS_REFRESH_TOKEN`, `TS_ACCOUNT_ID`, `TS_SIM`.

**Phase 3 deviations from `phase3_prompt.md` (residual after realignment):**
- Research-mode CSV infrastructure (`scripts/download_history.py`,
  `data/historical/SPY_1d.csv`) is in place ahead of schedule — spec puts
  it in Phase 4. Not used by `historical.py` yet (still serves stub data
  per spec). Easy to wire when Phase 4 starts.
- Spec said `GET /api/broker/status` (HX-Request) returns the topbar dot
  partial AND the account snapshot card uses the same endpoint. That
  conflicts (one URL can't serve both shapes meaningfully). Resolved by
  adding `GET /api/broker/account-card` for the snapshot card; topbar dot
  alone uses `/api/broker/status`.

### Phase 4 — Agents + Workflow Engine (see phase4_prompt.md for full spec)
Foundational rule: every pattern detector and analyst lens is a
**pure function of (bars, config, as_of_ts)** — no wall-clock calls,
no direct API calls, no mutable module state. This is what lets
Phase 5 replay the same code over 10+ years of historical bars.

14. `services/data_service.py` — yfinance bar cache, `as_of_ts`-aware slicing
15. `services/news_service.py` — Alpaca News (primary) + EDGAR filings,
    `as_of_ts`-aware for backtest replay. Alpha Vantage = optional sentiment
    enrichment only (kept behind a flag; skipped cleanly if absent)
16. `services/indicator_service.py` — pandas-ta wrapper (RSI, ATR, VWAP, squeeze, …)
17. `services/workflow_engine.py` — YAML-driven step DAG runner.
    Compliance + risk gates are NOT composable — engine injects them
    on every TradePlan, always, in that order. Workflow YAML that
    names a `compliance_officer` or `risk_manager` step is rejected.
18. `agents/compliance_officer.py` — gates C1–C8, unit tested
19. `agents/risk_manager.py` — gates R1–R9 pre-trade (postmortem → Phase 6)
20. `agents/universe_filter.py` — Finviz screener + pre-screener shortlist
21. `agents/analyst.py` — 4 lenses (technical, fundamental, sentiment, macro),
    9 pattern detectors, pure-function contract enforced
22. `agents/portfolio_manager.py` — signal synthesis → TradePlan
23. `services/pipeline_service.py` — thin orchestrator over WorkflowEngine
24. `services/db_service.py` — SQLite schema (pending_approvals, pipeline_runs,
    trade_memory) at `data/claude_trading_app.db` (in-project, gitignored)
25. `routers/workflows.py` — list/run workflows, pipeline status, universe latest
26. `workflows/*.yaml` — seed: morning_run, evening_run, research_run
27. `strategy_configs/swing_momentum.yaml` — pattern thresholds
28. `services/scheduler.py` — APScheduler reads each workflow's `schedule:`
    field; no hardcoded schedule list

### Phase 5 — Backtest Engine + Strategy Review (NEW — see SKILL.md §5 + phase5_prompt.md to be written)
Reuses every Phase 4 agent. Because detectors are pure functions of
`as_of_ts`, the backtest engine slides a window across 10+ years of
cached bars and calls the exact same code that runs live.

29. `services/backtest_engine.py` — walk-forward runner using vectorbt.
    Iterates `as_of_ts` across a bar range, calls WorkflowEngine.run()
    with historical timestamp, compliance+risk gates run as in live,
    simulated fills at next-bar open (configurable slippage/commission)
30. `services/backtest_report.py` — equity curve, CAGR, Sharpe, max DD,
    hit rate, avg R, exposure, per-strategy and per-pattern breakdowns
31. `models/backtest_result.py` — BacktestRun + per-trade records written
    to same TradeRecord JSONL schema as live (same ML feature pool)
32. `routers/backtests.py` — run, list, view, compare backtests
33. `templates/backtests/` — Strategy Review UI: backtest config form,
    equity curve chart, trade table, metrics dashboard. **Decision gate:**
    user marks a strategy `active` only after it clears 80% win-rate
    (or configured threshold) on a 10-year backtest
34. `agents/strategy_curator.py` (light) — reads backtest results,
    recommends parameter tweaks via walk-forward optimization

### Phase 6 — Approval flow + executioner + notifications (was Phase 5)
35. `agents/executioner.py` — BrokerAdapter calls, fill handling, live human-ack gate
36. `agents/risk_manager.py` (postmortem half) — MFE/MAE/R-multiple, learning tags
37. Full approval state machine: plan → compliance → risk → notify → ack → execute
38. `services/ntfy_service.py` — mobile push on every pending approval
39. Mobile-responsive CSS pass (pending page collapses 340px queue on <640px viewports)
40. Pending-detail ack flow with 15-minute countdown (already stubbed Phase 2, now real)

### Phase 7 — Memory, learning loop, polish (was Phase 6)
41. `services/memory_service.py` — SQLite similarity queries over trade_memory
42. `routers/trades.py` analysis tab — win rate, avg R, learning tags, cohort filters
43. `GET /api/sse/logs` + `templates/console.html` — live agent log stream
44. Dashboard widget becomes real (open positions + activity from live data)
45. Stub data fully removed from `services/stub_data.py`

---

## Key dependencies (requirements.txt)

```
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
jinja2>=3.1.4
python-multipart>=0.0.9
pydantic>=2.7.0
pydantic-settings>=2.3.0
httpx>=0.27.0
python-dotenv>=1.0.1
pyyaml>=6.0.1
apscheduler>=3.10.4
aiosqlite>=0.20.0
pandas>=2.2.0
numpy>=1.26.0
```

---

## Coding conventions Claude must follow in this project

1. **Pydantic v2** — use `model_validator`, `field_validator`, `model_dump()` not `.dict()`
2. **Async everywhere** — all FastAPI routes are `async def`; all I/O is awaited
3. **No print statements** — use Python `logging` module; logger per module
4. **Type hints on all function signatures** — no bare `dict` or `list` return types
5. **Settings injected, never imported globally** — use FastAPI `Depends(get_settings)`
6. **Broker adapter injected** — never instantiate adapters inside agent code
7. **HTMX responses** — partial template returns for HTMX requests (check `HX-Request` header)
8. **Error handling** — all agent methods return typed result objects; no bare exceptions
   propagating to routes. Routes return 422 with structured error body on agent failure.
9. **Comments on gate logic** — every compliance and risk gate method must have a docstring
   citing the rule it enforces (e.g. `"""Gate C4: Wash Sale Rule — IRC §1091"""`).
10. **No hardcoded paths** — import from `services.settings_service`
    (`PROJECT_ROOT`, `TRADE_LOG_DIR`, `LOCAL_DB_PATH`, etc.). Never hardcode
    `G:/_AgenticSkills`, `C:/g-jmk/trading_app`, `C:/g-jmk/My Drive/...`,
    or `C:/Temp/claude_trading_app.db` — those were all older layouts,
    superseded by the current `C:\Projects\TradingApp\` local layout.

---

## What Claude should NOT do in this project

- Do not add features not in the SKILL.md or this document without asking first
- Do not use SQLAlchemy ORM — raw `aiosqlite` only (keep it simple)
- Do not use a frontend JS framework (React, Vue) — HTMX + Jinja2 only
- Do not add authentication/login — this is a single-user local tool
- Do not modify the TradeRecord schema field names after first write to JSONL
- Do not call broker adapter methods outside of `executioner.py`
- Do not skip the compliance or risk gate in any code path, even in tests
- Do not store broker credentials in settings.yaml — `.env` only
- Do not instantiate `BrokerAdapter` subclasses anywhere except
  `services/broker_service.py`. All broker access goes through
  `get_adapter()` (added Phase 3).
- Do not store `TS_REFRESH_TOKEN` anywhere except `.env`. The adapter
  reads it on startup and writes the rotated token back to `.env` on
  every successful connect (added Phase 3).
- Do not use `position: fixed` in any template — iframe viewport issue.
  Use flow-positioned overlay `<div>` with `min-height` for modals
  (added Phase 3; HALT confirmation in `broker.html` is the reference
  implementation).
```
