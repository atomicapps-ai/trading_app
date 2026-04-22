# Session Handoff — 2026-04-22

Short catch-up doc for resuming in a fresh Claude Code session.
Read order: **CLAUDE.md** first (full spec + conventions), then this file.

---

## Current state

**Phases 1–4 substantially complete.**
One Phase 4 item remains: `services/scheduler.py` (APScheduler).
Phase 5 (Backtest Engine) is next.

---

## What was built in the most recent session (Universe Preset Manager)

The `/universe` page was upgraded from a static YAML detail view to a full
SQLite-backed preset CRUD manager with a Finviz filter editor.

### New files
- `services/finviz_catalog.json` — 76 usable Finviz filters (3 Elite-only removed).
  Each entry: `{id, label, tab, category, options[]}`. Committed; not re-scraped at runtime.
- `universe_filter_config.yaml` — 14 filter IDs shown by default in every preset editor:
  exch, cap, sh_price, sh_avgvol, sh_float, sh_short, ta_sma20, ta_sma50, ta_sma200,
  ta_rsi, ta_averagetruerange, sec, an_recom, earningsdate
- `templates/universe_edit.html` — full preset editor (new + edit modes):
  - Title input; auto-generates slug on new preset
  - 14 default filter rows (from config), each with SELECT dropdown + × remove
  - "+ Add filter" modal: searchable across all 76 filters, grouped by tab/category;
    already-added filters are greyed out
  - ▶ Run button — scrapes Finviz live, shows ticker count + list (no save)
  - "Save as universe" — persists tickers to SQLite after a test run

### Modified files
- `services/db_service.py` — added `universe_presets` table:
  `name, title, description, is_active, filters_json, tickers_json,
  output_tags_json, tickers_refreshed_at, updated_at, notes`.
  ALTER TABLE migration adds `title` to existing DBs (idempotent on startup).
- `services/universe_service.py` — added SQLite CRUD wrappers:
  `list_presets_db()`, `get_preset_db()`, `create_preset_db()`,
  `update_preset_db()`, `delete_preset_db()`, `set_active_preset_db()`,
  `save_preset_tickers_db()`, plus Finviz helpers: `load_finviz_catalog()`,
  `get_catalog_flat()`, `get_catalog_grouped()`, `load_filter_config()`,
  `scrape_finviz_filters()`, `seed_from_yaml_if_empty()`.
- `routers/universe.py` — full CRUD API (see routes below).
  Key fix: `set-active` returns `JSONResponse` with `HX-Redirect: /universe` header
  so HTMX reloads the page instead of trying to swap JSON into the preset list.
- `templates/universe.html` — list view: shows title + slug badge, ticker count,
  output_tags, clickable cards → edit page.
- `templates/universe_detail.html` — fixed stats-row alignment (`flex-start`),
  compact criteria padding, added "Edit / Run" button in header.
- `run.py` — fixed host to `127.0.0.1` (Windows socket perms), removed Unicode `→`.
- `.vscode/settings.json` — auto-activates venv in VSCode terminals.

### Universe API routes (all in `routers/universe.py`)
```
GET  /universe                             → preset list (SQLite)
GET  /universe/new                         → blank editor
GET  /universe/{name}/edit                 → edit existing preset
GET  /universe/{name}/detail               → legacy YAML read-only view
POST /api/universe/presets                 → create preset
POST /api/universe/presets/{name}          → update preset filters + metadata
POST /api/universe/presets/{name}/delete   → delete preset
POST /api/universe/presets/{name}/set-active    → mark as active
POST /api/universe/presets/{name}/test-run      → scrape Finviz, return tickers
POST /api/universe/presets/{name}/save-tickers  → persist ticker list
GET  /api/universe/catalog                 → full Finviz catalog JSON
GET  /api/universe/presets                 → JSON list
GET  /api/universe/presets/{name}          → JSON detail
GET  /api/universe/legacy                  → YAML-backed list (read-only)
GET  /api/universe/legacy/{name}           → YAML-backed detail
```

---

## Everything Phase 4 shipped (prior sessions)

### Core agents (all pure functions of `as_of_ts`)
- `agents/compliance_officer.py` — C1–C8 (halt, LULD, SSR, wash-sale, PDT,
  restricted list, earnings blackout, completeness). Advisory in research, hard in paper/live.
- `agents/risk_manager.py` — R1–R9 pre-trade. R1/R2/R8 resize; rest reject.
  Postmortem half deferred to Phase 6.
- `agents/universe_filter.py` — preset-driven shortlist; reads cached bars only.
- `agents/analyst.py` — technical + macro lenses live. 9 detectors live.
  Sentiment + fundamental lenses stubbed for Phase 6.
- `agents/macro.py` — SPY/VIX context (no signal, just inherited context).
- `agents/portfolio_manager.py` — signal consensus (3 OR-paths) → TradePlan;
  fixed-fractional sizing; existing-position + pending-queue guards.

### All 9 pattern detectors (`agents/detectors/`)
volatility_squeeze · inside_bar_nr7 · bull_flag · rsi_divergence · vwap_reclaim ·
double_bottom_top · ascending_triangle · cup_and_handle · wyckoff_accumulation

### Infrastructure
- `services/workflow_engine.py` — YAML DAG runner. Compliance+risk NOT composable.
- `services/pipeline_service.py` — orchestrates engine + gates + SQLite writes.
- `services/db_service.py` — `pending_approvals`, `pipeline_runs`, `trade_memory`,
  `universe_presets` tables. Idempotent migrations on startup.
- `routers/workflows.py` + `routers/bars.py` — both live.
- `workflows/morning_run.yaml`, `evening_run.yaml`, `research_run.yaml` seeded.
- `strategy_configs/swing_momentum.yaml` — thresholds for all 9 detectors.

### Alpaca as default broker
- `brokers/alpaca.py` — AlpacaAdapter via alpaca-py 0.43. Default for paper+live.
- `BROKER_PROVIDER=alpaca` (default). `BROKER_PROVIDER=tradestation` to opt in to TS.
- Env vars: `ALPACA_API_KEY` + `ALPACA_API_SECRET`.

### Executioner (brought forward from Phase 6)
- `agents/executioner.py` — gate re-check + HumanAckRecord freshness (15 min)
  → `BrokerAdapter.place_order()`. Research mode refuses all orders.
- `routers/pending.py` — approve path wired: HumanAckRecord → executioner → SQLite.

### /pending redesign
- Dual Lightweight Charts (replaced TradingView iframe). Two stacked panes,
  each with interval selector (1H/2H/4H/1D). Crosshair sync. Double-click scrolls
  sibling to hovered moment. Lazy-load older bars (300/page, `?before=<epoch>`).
- `routers/bars.py` — OHLCV; 2h/4h resampled from 1h cache.
- Plan levels (entry, stop, TP1, TP2) as labeled horizontal price-lines.
- Filter tabs; gate badge icons; approve disabled after 15-min expiry.

---

## One remaining Phase 4 item

`services/scheduler.py` — APScheduler that reads each workflow's `schedule:` cron
field and fires the pipeline automatically. Build this or skip to Phase 5 and return.

---

## What's next

### Option A: Finish Phase 4 (scheduler — ~1 hour)
`services/scheduler.py` — load workflows at startup, parse `schedule:` cron fields,
call `pipeline_service.run_workflow()` on each fire. APScheduler already in requirements.txt.
No hardcoded schedule list — all driven by workflow YAML.

### Option B: Start Phase 5 (Backtest Engine — 2–3 sessions)
Reuses every Phase 4 agent. Detectors are pure functions of `as_of_ts` so the engine
can slide a window across 10+ years of cached bars and call the exact same code.

Key new files:
- `services/backtest_engine.py` — walk-forward runner. Iterates `as_of_ts`,
  calls `pipeline_service.run_for_backtest(as_of_ts)`, simulates fills at next-bar open.
- `services/backtest_report.py` — equity curve, CAGR, Sharpe, max DD, hit rate, avg R.
- `models/backtest_result.py` — BacktestRun; per-trade records use same TradeRecord schema.
- `routers/backtests.py` + `templates/backtests/` — Strategy Review UI.
- **Decision gate:** user marks a strategy `active` only after clearing the configured
  win-rate threshold on a 10-year backtest.

### Option C: Test the Universe Preset Manager (incomplete as of handoff)
The Universe Preset Manager UI was just built but hasn't been fully tested end-to-end:
1. Start server: `python run.py dev` from `C:\Projects\trading_app` in VSCode terminal
2. Go to http://localhost:5000/universe
3. Create a new preset, configure some Finviz filters, click ▶ Run
4. If tickers come back, click "Save as universe" to persist
5. Verify the preset appears on the list page with ticker count

---

## How to bootstrap on a new machine

1. `git clone <repo_url> C:\Projects\trading_app`
2. `cd C:\Projects\trading_app`
3. `python -m venv .venv && .venv\Scripts\pip install -r requirements.txt`
4. Copy `.env` from password manager (see `.env.example` for required keys):
   - `ALPACA_API_KEY` + `ALPACA_API_SECRET` — required for paper trading
   - `BROKER_PROVIDER=alpaca` (or `tradestation`)
5. `cp settings.example.yaml settings.yaml` and edit
6. Copy `trade_logs/*.jsonl` from backup if available
7. `python -m scripts.smoke_alpaca_paper` — verifies broker connection
8. `python run.py dev` — starts server at http://localhost:5000

---

## Invariants (never violate)

- Compliance + risk gates run on **every** TradePlan. No workflow YAML can bypass them.
- Pattern detectors are pure functions of `(bars, config, as_of_ts)`. No `datetime.now()`.
- Broker credentials live only in `.env`. Never in `settings.yaml`, never in git.
- JSONL writes are append-only, one record per line, flush immediately.
- TradeRecord schema field names are frozen after first write.
- Live mode requires HumanAckRecord within 15 minutes before any order ships.
- Broker adapter selected via `BROKER_PROVIDER` env in `broker_service.py` only.
- Do NOT use TradingView iframe on `/pending` — replaced by Lightweight Charts in Phase 4.
- Do NOT re-scrape `finviz_catalog.json` at runtime — it's a committed static file.
