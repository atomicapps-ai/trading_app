# TradeAgent — Project Context for Claude Code
**Last synced:** 2026-04-22
**Status:** Phases 1–4 substantially complete. Phase 4 core (agents, workflow engine,
executioner, SQLite, /universe UI with SQLite-backed Finviz preset manager, dual-chart
/pending) all landed. One Phase 4 item remains: `services/scheduler.py` (APScheduler).
Phase 5 (Backtest Engine) is next.
**Roadmap (current):**
- Phase 4 ✅ (minus scheduler) — Agents + Workflow Engine + Executioner + UI polish
- Phase 5 NEXT — Backtest Engine + Strategy Review UI
- Phase 6 — ntfy push notifications + mobile CSS pass + risk_manager postmortem
- Phase 7 — Memory, learning loop, polish
**Companion docs:**
  - `SKILL.md` (project root) — domain logic
  - `phase2_prompt.md` (project root) — UI design system + per-screen layouts (still authoritative for any UI work)
  - `phase4_prompt.md` (project root) — Phase 4 agents + workflow engine spec (revised 2026-04-20)
**Stack:** FastAPI · HTMX 2.0.4 · Jinja2 · hand-rolled CSS (dark theme) · SQLite · JSONL · Tailscale · ntfy · **Alpaca** (default paper) · TradeStation (live)
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
  It never imports adapter modules directly — only the interface. `BROKER_PROVIDER` env var
  selects the adapter (`alpaca` default, `tradestation` opt-in). Research mode always uses
  `HistoricalAdapter` regardless of `BROKER_PROVIDER`.

---

## Project structure (current — as of Phase 4)

```
trading_app/
├── CLAUDE.md                    ← you are here
├── HANDOFF.md                   ← session catch-up doc
├── .env                         ← broker credentials, never committed
├── .gitignore
├── requirements.txt
├── app.py                       ← FastAPI entrypoint; mounts all routers + lifespan
│
├── agents/
│   ├── __init__.py
│   ├── universe_filter.py       ← preset-driven shortlist; SQLite-first (YAML fallback);
│   │                              _finviz_to_criteria() translates Finviz URL params to
│   │                              PrescreenCriteria; pure fn of (preset, as_of_ts)
│   ├── analyst.py               ← multi-lens runner: technical + macro lenses live;
│   │                              sentiment + fundamental lenses stubbed (Phase 6)
│   ├── macro.py                 ← SPY/VIX macro context snapshot (no signal, just context)
│   ├── portfolio_manager.py     ← signal consensus → TradePlan (fixed-fractional sizing)
│   ├── compliance_officer.py    ← gates C1–C8 (HALT, LULD, SSR, wash-sale, PDT,
│   │                              restricted list, earnings blackout, completeness)
│   ├── risk_manager.py          ← gates R1–R9 pre-trade; R1/R2/R8 resize, rest reject
│   │                              (postmortem half → Phase 6)
│   ├── executioner.py           ← ✅ Phase 4 (brought forward). Re-verifies all gates +
│   │                              HumanAckRecord freshness, then places order via
│   │                              BrokerAdapter. Research mode refuses all orders.
│   └── detectors/               ← 9 pattern detectors, all pure fn of (bars, config, as_of_ts)
│       ├── __init__.py          ← ALL_DETECTORS list + run_all() entry point
│       ├── _helpers.py          ← pivot_highs/lows, volume_ratio, wick helpers
│       ├── bull_flag.py
│       ├── inside_bar_nr7.py
│       ├── volatility_squeeze.py
│       ├── rsi_divergence.py
│       ├── vwap_reclaim.py
│       ├── double_bottom_top.py
│       ├── ascending_triangle.py
│       ├── cup_and_handle.py
│       └── wyckoff_accumulation.py
│
├── brokers/
│   ├── __init__.py
│   ├── base.py                  ← BrokerAdapter ABC + BrokerConnectionError
│   ├── historical.py            ← Research adapter (stub account + quotes)
│   ├── alpaca.py                ← ✅ Phase 4. Default paper+live broker via alpaca-py 0.43.
│   │                              connect() reads ALPACA_API_KEY/ALPACA_API_SECRET.
│   │                              Real orders, fills, account state, positions.
│   ├── tradestation.py          ← Opt-in (BROKER_PROVIDER=tradestation). OAuth
│   │                              refresh-token model; TS_REFRESH_TOKEN in .env.
│   └── webull.py                ← v1 stub: every method NotImplementedError.
│
├── scripts/
│   ├── download_history.py      ← yfinance bulk-downloader CLI
│   ├── refresh_universe.py      ← Finviz scrape → universe_filter_presets_tickers.yaml
│   ├── seed_demo_data.py        ← seeds pending_approvals + pipeline_runs in SQLite
│   ├── smoke_alpaca_paper.py    ← read-only real-API smoke (connect, account, quote)
│   ├── smoke_alpaca_order_roundtrip.py ← paper BUY→fill→SELL smoke
│   ├── smoke_data_coverage.py   ← bars + indicators + Alpaca NBBO for 6 tickers
│   ├── smoke_phase4_gates.py    ← compliance + risk gate unit smoke
│   ├── smoke_phase4_universe.py ← universe_filter end-to-end
│   ├── smoke_phase4_workflow.py ← WorkflowEngine DAG runner
│   ├── smoke_phase4_analyst.py  ← analyst lens + detectors
│   ├── smoke_phase4_portfolio_manager.py ← signals → TradePlan sizing
│   ├── smoke_phase4_pipeline.py ← pipeline_service + SQLite + /pending ack
│   ├── smoke_phase4_c3_executioner.py ← full approve → Alpaca order roundtrip
│   └── backup_trade_logs.ps1   ← robocopy trade_logs/ to Drive backup
│
├── models/
│   ├── __init__.py
│   ├── signal.py                ← Signal (+ pattern_name, entry/stop/tp prices)
│   ├── trade_plan.py            ← TradePlan (the central object)
│   ├── verdicts.py              ← ComplianceVerdict, RiskVerdict, HumanAckRecord
│   ├── trade_record.py          ← TradeRecord (JSONL schema — field names frozen)
│   ├── account.py               ← AccountState, Quote, Fill, Position, Order
│   ├── pattern.py               ← PatternResult (detector output)
│   ├── universe.py              ← UniverseFilterResult + preset schemas
│   └── execution.py             ← ExecutionResult (executioner output)
│
├── routers/
│   ├── __init__.py
│   ├── dashboard.py             ← GET /, /api/dashboard/{stats,agents,activity}
│   ├── pending.py               ← GET /pending, /pending/{id}; POST /pending/{id}/ack
│   │                              (approve → executioner; reject → DB flip).
│   │                              Reads SQLite (not stub data).
│   ├── trades.py                ← GET /trades, /trades/analysis, /api/trades
│   ├── settings.py              ← GET/POST /settings
│   ├── broker.py                ← /broker page + /api/broker/* endpoints + HALT
│   ├── bars.py                  ← GET /api/bars/{symbol}?interval=&limit=&before=
│   │                              OHLCV for Lightweight Charts; resamples 1h→2h/4h
│   ├── universe.py              ← GET /universe, /universe/{preset}; history API
│   ├── workflows.py             ← GET /api/workflows; POST /{id}/run;
│   │                              GET /api/pipeline/runs; GET /api/universe/latest
│   └── stubs.py                 ← Placeholders for /strategies, /console
│
├── services/
│   ├── __init__.py
│   ├── settings_service.py      ← Settings schema + path constants + UniverseUISettings
│   ├── log_service.py           ← Async JSONL append + read
│   ├── stub_data.py             ← Phase 2 stub data (dashboard/trades still stubbed)
│   ├── broker_service.py        ← Adapter factory (BROKER_PROVIDER env); TRADING_HALTED flag
│   ├── data_service.py          ← yfinance bar cache, as_of_ts-aware slicing
│   ├── news_service.py          ← Alpaca News + EDGAR filings, as_of_ts-aware
│   ├── indicator_service.py     ← 23 hand-rolled indicators (RSI, ATR, VWAP, squeeze, …)
│   ├── workflow_engine.py       ← YAML DAG runner. Compliance+risk NOT composable —
│   │                              engine rejects workflow YAML that names those steps.
│   ├── pipeline_service.py      ← Thin orchestrator: engine + gates + SQLite writes
│   ├── db_service.py            ← aiosqlite layer: pending_approvals, pipeline_runs,
│   │                              trade_memory tables + full CRUD
│   ├── universe_service.py      ← SQLite CRUD wrappers (list/get/create/update/delete/
│   │                              set_active/save_tickers) + Finviz catalog helpers:
│   │                              load_finviz_catalog(), get_catalog_flat/grouped(),
│   │                              load_filter_config(), scrape_finviz_filters(),
│   │                              seed_from_yaml_if_empty()
│   └── finviz_catalog.json      ← 76 usable Finviz filters (Elite-only stripped).
│                                   Each entry: {id, label, tab, category, options[]}.
│                                   Parsed once from Finviz HTML; committed to repo.
│
├── templates/
│   ├── base.html                ← Shell: sidebar, topbar, mode badge, ET clock, HALT
│   ├── _placeholder.html        ← "Coming in Phase X" generic page
│   ├── dashboard.html + dashboard/
│   ├── pending.html             ← Split layout: 340px queue + dual Lightweight Charts
│   │                              (2 panes, interval selector, crosshair sync,
│   │                              dblclick scroll, lazy-load older bars).
│   │                              Reads SQLite. Approve flow wires to executioner.
│   ├── trades.html + trades/
│   ├── settings.html + settings/
│   ├── broker.html
│   ├── universe.html            ← Preset list: title + slug badge, ticker count,
│   │                              last-refresh ts, output_tags badges, set-active /
│   │                              edit / delete buttons. Cards clickable → edit page.
│   ├── universe_edit.html       ← Preset editor (new + edit modes):
│   │                              · Title input (auto-generates slug on new)
│   │                              · 14 default filter rows from universe_filter_config.yaml;
│   │                                each row = label + SELECT dropdown (all options from
│   │                                finviz_catalog.json) + × remove button
│   │                              · "+ Add filter" modal: searchable across all 76 filters,
│   │                                grouped by tab/category; already-added greyed out
│   │                              · ▶ Run button — scrapes Finviz live, shows ticker count
│   │                              · Save as universe — persists tickers to SQLite
│   └── universe_detail.html     ← Legacy YAML detail: Criteria / Tickers / History tabs;
│                                  settings-driven include/exclude/pinned field visibility
│
├── workflows/
│   ├── morning_run.yaml
│   ├── evening_run.yaml
│   └── research_run.yaml
│
├── strategy_configs/
│   └── swing_momentum.yaml      ← Pattern thresholds for all 9 detectors
│
├── universe_filter_presets.yaml          ← Legacy YAML criteria (read-only after SQLite migration)
├── universe_filter_presets_tickers.yaml  ← Seed ticker list (committed; overwritten by refresh)
├── universe_filter_config.yaml           ← 14 default-visible filter IDs shown in every preset
│                                           editor: exch, cap, sh_price, sh_avgvol, sh_float,
│                                           sh_short, ta_sma20, ta_sma50, ta_sma200, ta_rsi,
│                                           ta_averagetruerange, sec, an_recom, earningsdate
│
├── static/
│   ├── app.css                  ← Hand-rolled dark-theme CSS (~500 lines)
│   └── htmx.min.js              ← HTMX 2.0.4 localized
│
└── data/                        ← gitignored
    ├── logs/
    ├── historical/              ← yfinance CSVs
    ├── news_cache/
    ├── edgar_cache/
    ├── universe_history/        ← archived preset snapshots (criteria + tickers)
    └── claude_trading_app.db    ← SQLite; auto-created on startup
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
GET  /universe                      → universe.html (SQLite preset list)
GET  /universe/new                 → universe_edit.html (blank preset form)
GET  /universe/{name}/edit         → universe_edit.html (edit existing preset)
GET  /universe/{name}/detail       → universe_detail.html (legacy YAML read-only view)
POST /api/universe/presets         → create preset (form: name, title, description, tags)
POST /api/universe/presets/{name}  → update preset (filters + metadata)
POST /api/universe/presets/{name}/delete    → delete preset
POST /api/universe/presets/{name}/set-active → mark active (HX-Redirect header)
POST /api/universe/presets/{name}/test-run  → scrape Finviz, return tickers (no save)
POST /api/universe/presets/{name}/save-tickers → persist ticker list to SQLite
POST /api/universe/presets/{name}/run-agent  → run in-process UniverseFilter screener on saved tickers
GET  /api/universe/catalog         → full Finviz filter catalog JSON (76 filters)
GET  /api/universe/presets         → JSON list of all presets
GET  /api/universe/presets/{name}  → JSON detail for one preset
GET  /api/universe/legacy          → JSON list (YAML-backed, read-only)
GET  /api/universe/legacy/{name}   → JSON detail (YAML-backed)
GET  /api/universe/latest          → JSON: last universe_result
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

## Chart implementation on /pending (Phase 4)

TradingView was replaced with dual Lightweight Charts panes (no API key, no iframe).
Data comes from `GET /api/bars/{symbol}?interval=<1h|2h|4h|1d>&limit=500&before=<epoch>`.
- Two stacked panes; each has its own interval selector (1H / 2H / 4H / 1D).
- Crosshair hover on one pane syncs the crosshair on the other at the matching timestamp.
- Double-click on a pane scrolls the other pane to center on the hovered moment,
  preserving each chart's current visible bar count (logical range, not time-width).
- Lazy-load: scrolling to the left edge fetches 300 more bars via `?before=<epoch>`;
  stops when the server returns `has_more=false`.
- Plan levels (entry, stop, TP1, TP2) render as labeled horizontal price-lines.
- 2h/4h intervals are resampled server-side from the 1h cache via pandas.

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

### Phase 4 — Agents + Workflow Engine — ✅ SUBSTANTIALLY COMPLETE 2026-04-22
Foundational rule: every pattern detector and analyst lens is a
**pure function of (bars, config, as_of_ts)** — no wall-clock calls,
no direct API calls, no mutable module state. This is what lets
Phase 5 replay the same code over 10+ years of historical bars.

14. ✅ `services/data_service.py` — yfinance bar cache, `as_of_ts`-aware slicing
15. ✅ `services/news_service.py` — Alpaca News (primary) + EDGAR, `as_of_ts`-aware
16. ✅ `services/indicator_service.py` — 23 hand-rolled indicators (no pandas-ta)
17. ✅ `services/workflow_engine.py` — YAML DAG runner. Compliance + risk NOT composable;
    engine rejects workflow YAML that names those steps.
18. ✅ `agents/compliance_officer.py` — gates C1–C8 (mode-aware: advisory in research,
    enforced in paper/live)
19. ✅ `agents/risk_manager.py` — gates R1–R9 pre-trade; R1/R2/R8 resize, rest reject
    (postmortem half deferred to Phase 6)
20. ✅ `agents/universe_filter.py` — preset-driven shortlist; reads cached bars only,
    no network. `scripts/refresh_universe.py` handles periodic Finviz scrape separately.
21. ✅ `agents/analyst.py` + `agents/detectors/` — technical lens + macro context live;
    all 9 pattern detectors live (volatility_squeeze, inside_bar_nr7, bull_flag,
    rsi_divergence, vwap_reclaim, double_bottom_top, ascending_triangle,
    cup_and_handle, wyckoff_accumulation). Sentiment + fundamental lenses stubbed.
22. ✅ `agents/portfolio_manager.py` — signal consensus (3 OR-paths) → TradePlan;
    fixed-fractional position sizing; existing-position + pending-queue guards.
23. ✅ `services/pipeline_service.py` — enforces compliance-then-risk invariant;
    persists every plan + verdicts to SQLite.
24. ✅ `services/db_service.py` — pending_approvals, pipeline_runs, trade_memory;
    ALTER TABLE migrations run idempotently on startup.
25. ✅ `routers/workflows.py` — GET /api/workflows; POST /{id}/run; pipeline history
26. ✅ `workflows/*.yaml` — morning_run, evening_run, research_run seeded
27. ✅ `strategy_configs/swing_momentum.yaml` — thresholds for all 9 detectors
28. ⬜ `services/scheduler.py` — APScheduler reads each workflow's `schedule:` field.
    **Only remaining Phase 4 item.**

**Phase 4 extras (not in original spec):**
- ✅ `brokers/alpaca.py` — AlpacaAdapter. Default paper+live broker. TradeStation
  gates real-money API behind a $10k minimum; Alpaca unblocks the paper workflow.
  `BROKER_PROVIDER=alpaca` (default), `BROKER_PROVIDER=tradestation` to opt in to TS.
- ✅ `agents/executioner.py` — **brought forward from Phase 6**. Full click-path:
  POST /pending/{id}/ack?action=approve → gate re-checks → HumanAckRecord freshness
  → BrokerAdapter.place_order(). Research mode refuses all orders.
- ✅ `models/execution.py` — ExecutionResult (placed bool + broker_order_id + reason)
- ✅ `routers/bars.py` — OHLCV endpoint for Lightweight Charts; 2h/4h resampled from 1h
- ✅ `/pending` redesign — dual Lightweight Charts (replaced TradingView iframe);
  crosshair sync, dblclick scroll, lazy-load older bars, filter tabs, gate icons,
  expiry enforcement, approve disabled on expiry.
- ✅ `/universe` full preset manager — SQLite-backed CRUD for named presets.
  Each preset has a human-readable `title` + machine `name` slug + `description` +
  `output_tags` + `filters` dict (Finviz key → option value).
  - `services/finviz_catalog.json` — 76 usable Finviz filters (3 Elite-only removed).
    Each filter has id, label, tab, category, options[]. Committed; not re-scraped at runtime.
  - `universe_filter_config.yaml` — 14 filter IDs shown by default in every preset editor.
  - `services/db_service.py` — `universe_presets` table: name, title, description,
    is_active, filters_json, tickers_json, output_tags_json, tickers_refreshed_at,
    updated_at. ALTER TABLE migration adds `title` column to existing DBs.
  - `services/universe_service.py` — CRUD wrappers + Finviz catalog helpers +
    `scrape_finviz_filters()` + `seed_from_yaml_if_empty()` (one-time YAML→SQLite migration).
  - `templates/universe_edit.html` — full filter editor: 14 default rows + searchable
    "+ Add filter" modal (76 filters grouped by tab/category) + ▶ Run + Save as universe.
  - `templates/universe.html` — list view: title + slug, clickable cards → edit,
    ▶ Agent button (per card, if tickers saved) → POST /run-agent → modal with
    shortlist count, full universe, rejection breakdown, run duration.
  - `templates/universe_detail.html` — legacy YAML detail; fixed layout (compact rows,
    flex-start alignment); added "Edit / Run" button linking to edit page.
  - `agents/universe_filter.py` — now SQLite-first: tries `_load_sqlite_preset()` before
    YAML fallback. `_finviz_to_criteria()` maps Finviz URL params to PrescreenCriteria.
  - `POST /api/universe/presets/{name}/run-agent` — runs in-process UniverseFilter on
    saved tickers; returns shortlist + rejection stats; 422 if no tickers saved.
  - `static/app.css` — added `--font-mono`, `--surface-1/2/3` CSS variables to `:root`
    (were missing; `universe_edit.html` and agent modal depend on them). Also `.mt-8`.
- ✅ `services/universe_service.py` — preset list/detail/archive
- ✅ `universe_filter_presets_tickers.yaml` — seed list (25 liquid names)

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

### Phase 6 — Notifications + risk postmortem + mobile polish
(Executioner was brought forward to Phase 4; approval state machine is live.)
35. ✅ ~~`agents/executioner.py`~~ — done in Phase 4
36. `agents/risk_manager.py` (postmortem half) — MFE/MAE/R-multiple, learning tags
37. `services/ntfy_service.py` — mobile push on every new pending approval
38. `agents/analyst.py` — wire sentiment lens (VADER on Alpaca headlines) and
    fundamental lens (EDGAR/Alpaca fundamentals); both stubbed in Phase 4
39. Mobile-responsive CSS pass (pending page collapses 340px queue on <640px viewports)

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
- Do not store `TS_REFRESH_TOKEN` or `ALPACA_API_KEY`/`ALPACA_API_SECRET` anywhere
  except `.env`. The TradeStation adapter writes the rotated token back to `.env`
  on every successful connect.
- Do not use `position: fixed` in any template — iframe viewport issue.
  Use flow-positioned overlay `<div>` with `min-height` for modals
  (HALT confirmation in `broker.html` is the reference implementation).
- Do not use a TradingView iframe on `/pending` — it was replaced with dual
  Lightweight Charts in Phase 4. Use `GET /api/bars/{symbol}` for chart data.
- Do not hardcode broker selection — always use `BROKER_PROVIDER` env var
  (default `alpaca`; `tradestation` opt-in). `broker_service.py` handles the switch.
- Do not re-scrape the Finviz filter catalog at runtime — it's committed as
  `services/finviz_catalog.json`. Only update by running the one-off scrape script.
- Do not hardcode filter IDs in templates — always source from `universe_filter_config.yaml`
  (default-visible set) and `finviz_catalog.json` (full catalog).
- Do NOT re-define `--surface-1/2/3` or `--font-mono` in page templates —
  they live in `static/app.css` `:root` block.
- In Jinja2 templates, macros MUST be defined before their first call site.
  Jinja2 does not hoist macro definitions — a `{% macro %}` block at the bottom
  of the file cannot be called from a block above it. Always define macros at
  the top of the `{% block content %}` before any use.
```

---

## Starting the server (developer workflow)

Open the project folder in VSCode. The `.vscode/settings.json` auto-activates the venv
in every new terminal. Then run:

```
python run.py dev    # hot-reload, info logging → http://localhost:5000
python run.py prod   # 2 workers, warning logging → http://localhost:5000
```

Binds to `127.0.0.1:5000` (not `0.0.0.0` — Windows firewall blocks that port on 0.0.0.0).
