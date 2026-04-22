# Session Handoff — 2026-04-22

Short catch-up doc for resuming work on a different machine or in a fresh
Claude Code session. Start of any new chat: read `CLAUDE.md` first, then
this file, then `phase4_prompt.md` (still authoritative for Phase 4 conventions).

## Current state (as of 2026-04-22)

**Phases 1–4 substantially complete.** One Phase 4 item remains
(`services/scheduler.py`). The full agent pipeline runs end-to-end:
universe filter → analyst (9 detectors) → portfolio manager → compliance
gates → risk gates → executioner → Alpaca paper order.

### What Phase 4 shipped

**Core agents (all pure functions of `as_of_ts`):**
- `agents/compliance_officer.py` — C1–C8 (halt, LULD, SSR, wash-sale, PDT,
  restricted list, earnings blackout, completeness). Advisory in research, hard in paper/live.
- `agents/risk_manager.py` — R1–R9 pre-trade. R1/R2/R8 resize; rest reject.
  Postmortem half deferred to Phase 6.
- `agents/universe_filter.py` — preset-driven shortlist; reads cached bars only.
- `agents/analyst.py` — technical + macro lenses live. 9 detectors live (see below).
  Sentiment + fundamental lenses stubbed for Phase 6.
- `agents/macro.py` — SPY/VIX context (no signal, just inherited context).
- `agents/portfolio_manager.py` — signal consensus (3 OR-paths) → TradePlan with
  fixed-fractional sizing. Existing-position + pending-queue guards.

**All 9 pattern detectors live (`agents/detectors/`):**
volatility_squeeze · inside_bar_nr7 · bull_flag · rsi_divergence · vwap_reclaim ·
double_bottom_top · ascending_triangle · cup_and_handle · wyckoff_accumulation

**Infrastructure:**
- `services/workflow_engine.py` — YAML DAG runner. Compliance + risk
  are NOT workflow steps — engine rejects YAML that names them.
- `services/pipeline_service.py` — orchestrates engine + gates + SQLite writes.
- `services/db_service.py` — `pending_approvals`, `pipeline_runs`, `trade_memory`
  tables. ALTER TABLE migrations run idempotently on startup.
- `services/universe_service.py` — preset list/detail/archive.
- `routers/workflows.py` + `routers/bars.py` + `routers/universe.py` — all live.
- `workflows/morning_run.yaml`, `evening_run.yaml`, `research_run.yaml` seeded.
- `strategy_configs/swing_momentum.yaml` — thresholds for all 9 detectors.

**Alpaca as default broker:**
- `brokers/alpaca.py` — AlpacaAdapter via alpaca-py 0.43. Default for paper+live.
  TradeStation blocks paper trading behind a $10k funded-account minimum; Alpaca
  unblocks the workflow at zero cost.
- `BROKER_PROVIDER=alpaca` (default). Set `BROKER_PROVIDER=tradestation` to opt in to TS.
- New env vars: `ALPACA_API_KEY` + `ALPACA_API_SECRET` (or the `ALPACA_TRADING_*` pair).
- Smoke-tested: `smoke_alpaca_paper.py` (read-only), `smoke_alpaca_order_roundtrip.py`
  (BUY→fill→SELL net-flat).

**Executioner brought forward from Phase 6:**
- `agents/executioner.py` — full gate re-check + HumanAckRecord freshness (15 min)
  → `BrokerAdapter.place_order()`. Research mode refuses all orders.
- `models/execution.py` — ExecutionResult (placed bool + broker_order_id + reason).
- `routers/pending.py` — approve path wired: builds HumanAckRecord → executioner →
  persists ExecutionResult. Rejects 409 on repeated approvals (idempotent).
- `scripts/smoke_phase4_c3_executioner.py` — end-to-end smoke: research plan refused,
  paper plan placed on Alpaca, order verified in /v2/orders, cleaned up.

**UI overhaul on /pending:**
- Dual Lightweight Charts (replaced TradingView iframe). Two stacked panes, each with
  interval selector (1H/2H/4H/1D). Crosshair hover syncs between panes. Double-click
  scrolls sibling pane to the hovered moment (logical-range, not time-width). Lazy-load
  older bars on left-edge scroll (300 bars/page, `?before=<epoch>` pagination).
- `routers/bars.py` — OHLCV endpoint; 2h/4h resampled server-side from 1h cache.
- Plan levels (entry, stop, TP1, TP2) rendered as labeled horizontal price-lines.
- Filter tabs (pending/approved/rejected/all); filter preserved on row-click navigation.
- Gate badge icons: shield = compliance, scale = risk. Status-pill icons on plan cards.
  Outcome glyphs on closed plans.
- Approve button disabled after 15-minute expiry. Auto-expiry marks stale plans.

**Real /universe pages:**
- `/universe` — preset list with strategy affinity (from output_tags), ticker count,
  last-refresh ts, source tag, archived-version counts.
- `/universe/{preset}` — Criteria / Tickers / History tabs. Criteria grouped by category
  (Price & Volume / Size / Profitability / Technical / Volatility / Short interest /
  Exchange & sector / Other). Tickers joined with prescreener scores from the most recent
  pipeline run. History lists every archived snapshot (criteria + tickers), each linkable.
- Settings-driven panel: `settings.yaml → universe.ui` lets you include/exclude/pin
  specific criteria fields without touching the preset YAML. Hidden fields are listed
  in an amber card as a reminder they're still applied server-side.

## One remaining Phase 4 item

`services/scheduler.py` — APScheduler that reads each workflow's `schedule:` field
and fires the pipeline automatically. Nothing else is pending in Phase 4. Build this
or skip to Phase 5 and come back.

## What's next

### Option A: Finish Phase 4 (scheduler — ~1 hour)
- `services/scheduler.py` — load workflows at startup, parse `schedule:` cron fields,
  call `pipeline_service.run_workflow()` on each fire. APScheduler already in
  `requirements.txt`. No hardcoded schedule list — all driven by workflow YAML.

### Option B: Start Phase 5 (Backtest Engine)
Reuses every Phase 4 agent unchanged. Because detectors are pure functions of
`as_of_ts`, the backtest engine slides a window across 10+ years of cached bars
and calls the exact same code that runs live.

Key new files for Phase 5:
- `services/backtest_engine.py` — walk-forward runner. Iterates `as_of_ts` across a
  bar range, calls `pipeline_service.run_for_backtest(as_of_ts)`, simulates fills at
  next-bar open (configurable slippage/commission).
- `services/backtest_report.py` — equity curve, CAGR, Sharpe, max DD, hit rate, avg R.
- `models/backtest_result.py` — BacktestRun schema; per-trade records written to the
  same TradeRecord JSONL schema as live (same ML pool).
- `routers/backtests.py` + `templates/backtests/` — Strategy Review UI.
- **Decision gate:** user marks a strategy `active` only after clearing the configured
  win-rate threshold on a 10-year backtest.

## How to bootstrap on a new machine

1. `git clone <repo_url> C:\Projects\TradingApp`
2. `python -m venv .venv && .venv\Scripts\pip install -r requirements.txt`
3. Copy `.env` from password manager (see `.env.example` for required keys):
   - `ALPACA_API_KEY` + `ALPACA_API_SECRET` — required for paper trading (default broker)
   - `TS_CLIENT_ID` + `TS_CLIENT_SECRET` + `TS_REFRESH_TOKEN` + `TS_ACCOUNT_ID` — TS opt-in
   - `BROKER_PROVIDER=alpaca` (default) or `tradestation`
4. `cp settings.example.yaml settings.yaml` and edit (or copy from source machine)
5. Copy `trade_logs/*.jsonl` from backup if available
6. `python -m scripts.smoke_alpaca_paper` — verifies broker connection
7. `python -m scripts.smoke_phase4_pipeline` — verifies full pipeline + SQLite

## Important invariants (do not violate)

- Compliance + risk gates run on **every** TradePlan. No workflow YAML can bypass them.
- Pattern detectors are pure functions of `(bars, config, as_of_ts)`. No `datetime.now()`.
- Broker credentials live only in `.env`. Never in `settings.yaml`, never in git.
- JSONL writes are append-only, one record per line, flush immediately.
- TradeRecord schema field names are frozen after first write.
- Live mode requires a HumanAckRecord within 15 minutes before any order ships.
- Broker adapter selected via `BROKER_PROVIDER` env in `broker_service.py` only.
  Never instantiate `BrokerAdapter` subclasses outside `broker_service.py`.
- Do NOT use TradingView iframe on `/pending` — replaced by Lightweight Charts in Phase 4.
