# Session Handoff — 2026-04-22

Short catch-up doc for resuming in a fresh Claude Code session.
Read order: **CLAUDE.md** first (full spec + conventions), then this file.

---

## Current state

**Phases 1–4 substantially complete.**
One Phase 4 item remains: `services/scheduler.py` (APScheduler).
Phase 5 (Backtest Engine) is next.

---

## What was fixed / built in the most recent session

### Bug fix — `templates/universe_edit.html` (Jinja2 macro ordering)
The preset edit page (`/universe/{name}/edit`) was a hard 500 for any
existing preset. Root cause: the `filter_row` Jinja2 macro was defined
at the bottom of the template after the call sites, and called with
invalid `self::filter_row()` Rust-style syntax. Fixed: macro moved
above its first use inside `{% block content %}`, calls corrected to
`filter_row()`.

### New — `agents/universe_filter.py` SQLite-first loading
`UniverseFilter.run()` now tries SQLite before falling back to the legacy
YAML files. Two new helpers:
- `_finviz_to_criteria(filters)` — translates Finviz filter param strings
  (e.g. `sh_price=o10`, `ta_sma50=pa`, `sh_avgvol=o1000`, `ta_rsi=ob70`)
  into `PrescreenCriteria` for the in-process screener. ATR skipped (Finviz
  uses absolute $; criteria needs atr_pct %).
- `_load_sqlite_preset(preset_name)` — async; reads tickers + filters from
  SQLite via `universe_service.get_preset_db()`. Returns None if preset not
  found or has no saved tickers (→ YAML fallback).

### New — `POST /api/universe/presets/{name}/run-agent`
Runs the in-process UniverseFilter screener on a preset's saved tickers.
Returns `{shortlist, universe, total_screened, rejected_count,
rejection_reasons, run_duration_seconds}`. Returns 422 if no tickers saved.

### New — ▶ Agent button on `/universe` list page
Each preset card with saved tickers now shows a blue `▶ Agent` button.
Clicking it calls `/run-agent`, shows a modal with shortlist count, full
universe, rejection breakdown, and run duration. No page reload required.

### CSS fix — `static/app.css`
Added missing CSS variables that `universe_edit.html` and the agent modal
depend on:
```css
--font-mono: ui-monospace, SFMono-Regular, "SF Mono", Consolas, monospace;
--surface-1: #0f1117;   /* darkest — readonly/disabled inputs */
--surface-2: #141720;   /* standard input background */
--surface-3: #1a1d27;   /* elevated — hover states */
```
Also added `.mt-8 { margin-top: 8px; }` utility class.

### Open issue — browser native `<select>` styling on Windows
On Windows Chrome/Edge, native `<select>` elements may ignore
`background` CSS and render with OS-default white/gray even when
`background: var(--surface-2)` is set. This causes the filter dropdowns
in `universe_edit.html` to appear light-themed. The full fix requires
either custom `<select>` styling (appearance: none + SVG arrow) or
replacing `<select>` with a custom dropdown component. **Not yet fixed —
prioritise in the next session if the dark theme still looks broken.**

---

## Universe API routes (all in `routers/universe.py`)

```
GET  /universe                             → preset list (SQLite)
GET  /universe/new                         → blank editor
GET  /universe/{name}/edit                 → edit existing preset
GET  /universe/{name}/detail               → legacy YAML read-only view
POST /api/universe/presets                 → create preset
POST /api/universe/presets/{name}          → update preset filters + metadata
POST /api/universe/presets/{name}/delete   → delete preset
POST /api/universe/presets/{name}/set-active    → mark as active (HX-Redirect)
POST /api/universe/presets/{name}/test-run      → scrape Finviz, return tickers
POST /api/universe/presets/{name}/save-tickers  → persist ticker list to SQLite
POST /api/universe/presets/{name}/run-agent     → in-process prescreen → shortlist
GET  /api/universe/catalog                 → full Finviz catalog JSON (76 filters)
GET  /api/universe/presets                 → JSON list
GET  /api/universe/presets/{name}          → JSON detail
GET  /api/universe/legacy                  → YAML-backed list (read-only)
GET  /api/universe/legacy/{name}           → YAML-backed detail
```

---

## End-to-end universe flow (as of this session)

```
1. /universe          → see preset list
2. + New preset       → title → slug → redirect to /universe/{name}/edit
3. Edit page          → 14 default filter rows + "+ Add filter" modal (76 catalog filters)
                        Configure filters → Save (POST .../presets/{name})
4. ▶ Run             → POST .../test-run → Finviz live scrape → ticker count + list
5. Save as universe   → POST .../save-tickers → tickers persisted to SQLite
6. ▶ Agent (list)    → POST .../run-agent → in-process bar screener → ranked shortlist
7. Set active         → POST .../set-active → HX-Redirect reloads list
```

---

## Everything Phase 4 shipped (prior sessions)

### Core agents (all pure functions of `as_of_ts`)
- `agents/compliance_officer.py` — C1–C8 (halt, LULD, SSR, wash-sale, PDT,
  restricted list, earnings blackout, completeness). Advisory in research, hard in paper/live.
- `agents/risk_manager.py` — R1–R9 pre-trade. R1/R2/R8 resize; rest reject.
  Postmortem half deferred to Phase 6.
- `agents/universe_filter.py` — SQLite-first shortlist (falls back to YAML).
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

### Priority: Fix `<select>` dark theme on Windows (quick)
Browser native `<select>` elements ignore `background` CSS on Windows
Chrome/Edge. Fix options:
- **Option A (recommended):** Add `appearance: none` to `.filter-select`
  in `universe_edit.html` and supply a custom SVG dropdown arrow via CSS.
- **Option B:** Replace the filter `<select>` with a custom JS dropdown
  (more work, better cross-browser control).

### Option A: Finish Phase 4 (scheduler — ~1 hour)
`services/scheduler.py` — load workflows at startup, parse `schedule:` cron fields,
call `pipeline_service.run_workflow()` on each fire. APScheduler already in requirements.txt.

### Option B: Start Phase 5 (Backtest Engine — 2–3 sessions)
Reuses every Phase 4 agent. Detectors are pure functions of `as_of_ts` so the engine
can slide a window across 10+ years of cached bars and call the exact same code.

Key new files:
- `services/backtest_engine.py` — walk-forward runner. Iterates `as_of_ts`,
  calls `pipeline_service.run_for_backtest(as_of_ts)`, simulates fills at next-bar open.
- `services/backtest_report.py` — equity curve, CAGR, Sharpe, max DD, hit rate, avg R.
- `models/backtest_result.py` — BacktestRun; per-trade records use same TradeRecord schema.
- `routers/backtests.py` + `templates/backtests/` — Strategy Review UI.

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
7. `python run.py dev` — starts server at http://localhost:5000

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
- Do NOT re-define `--surface-1/2/3` or `--font-mono` in page templates —
  they live in `static/app.css` `:root` block.
