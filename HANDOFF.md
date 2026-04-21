# Session Handoff — 2026-04-20

Short catch-up doc for resuming work on a different machine or in a fresh
Claude Code session. Start of any new chat: read `CLAUDE.md` first, then
this file, then the current `phase4_prompt.md`.

## Current state (as of 2026-04-20)

- **Phases 1–3 complete** (Foundation, UI shell, Broker layer).
- **Phase 4 Steps 1–3 complete and smoke-tested** on this branch:
  - `services/data_service.py` — yfinance bar cache, `as_of_ts`-aware slicing
  - `services/news_service.py` — Alpaca News + EDGAR, `as_of_ts`-aware
  - `services/indicator_service.py` — 23 indicators hand-rolled (no pandas-ta)
- **Infrastructure overhaul 2026-04-20**:
  - Project relocated from `C:\g-jmk\My Drive\_TradingApp\` → `C:\Projects\TradingApp\` (off Drive)
  - Python upgraded 3.12 → 3.14.4 (3.12 install went missing; 3.14 wheels
    resolved cleanly for pandas 3.0, numpy 2.4, alpaca-py 0.43, yfinance 1.3)
  - SQLite moved from `C:/Temp/` carve-out to in-project `data/claude_trading_app.db`
  - `.gitignore`, `settings.example.yaml`, `scripts/backup_trade_logs.ps1` added
  - `CLAUDE.md` storage section rewritten for single-location layout

## Phase 4 spec revisions (logged in CLAUDE.md + phase4_prompt.md)

The original Phase 4 was "just agents." It was expanded on 2026-04-20 to include:
1. **Workflow engine** — `workflows/*.yaml` composable DAG runner. Compliance + risk
   gates are NOT composable — engine injects them on every TradePlan.
2. **Alpaca News** promoted to primary news source (Benzinga-sourced, free, ~2015+ archive).
   Alpha Vantage demoted to optional sentiment enrichment.
3. **Pure-function detector contract** — every pattern detector and analyst lens
   takes `as_of_ts` as its only "now." No `datetime.now()`, no live API calls.
   This is what enables Phase 5 backtesting to replay 10+ years of bars using
   the same code that runs live.
4. **VADER sentiment** for backtest-safe headline scoring.

## Roadmap revision 2026-04-20

- Phase 4 (next steps 4–14): Agents + Workflow Engine
- **Phase 5 NEW**: Backtest Engine + Strategy Review UI (was Approval flow)
- Phase 6: Approval flow + executioner + ntfy + mobile CSS pass (was Scheduler)
- Phase 7: Memory, learning loop, polish (was Phase 6)

Rationale: strategies must be validated over 10+ years of bars before the
live executioner is wired up. Detectors must be pure functions for this to
work — hence the Phase 4 contract above.

## What's next (remaining Phase 4 steps)

In order from `phase4_prompt.md`:

4. `agents/universe_filter.py` — Finviz scraper + pre-screener shortlist
5. `agents/analyst.py` — 4 lenses, 9 pattern detectors, PQS scoring (the big one)
6. `agents/compliance_officer.py` — gates C1–C8
7. `agents/risk_manager.py` — gates R1–R9 pre-trade
8. `agents/portfolio_manager.py` — signals → TradePlan synthesis
9. `services/workflow_engine.py` — YAML DAG runner
10. `services/pipeline_service.py` — thin orchestrator around workflow_engine
11. `services/db_service.py` — SQLite schema (pending_approvals, pipeline_runs, trade_memory)
12. `routers/workflows.py` — `/api/workflows/*` endpoints; update `routers/pending.py` to read SQLite
13. `routers/stubs.py` — drop `/universe` stub (now real)
14. `services/scheduler.py` — APScheduler reads each workflow's `schedule:` field
15. `strategy_configs/swing_momentum.yaml` — pattern thresholds
16. Seed `workflows/morning_run.yaml`, `evening_run.yaml`, `research_run.yaml`

My suggested next session order: 6 + 7 first (compliance + risk gates are
self-contained and unit-test-driven), then 4 (universe_filter), then 9
(workflow_engine), then 5 (analyst — the biggest chunk), then the rest.

## How to bootstrap on a new machine

1. `git clone <repo_url> C:\Projects\TradingApp` (or wherever you want)
2. `cd C:\Projects\TradingApp`
3. `python -m venv .venv`
4. `.venv\Scripts\pip install -r requirements.txt`
5. Copy `.env` from your password manager (NOT from git — it's gitignored)
6. Copy `settings.yaml` from the source machine, OR `cp settings.example.yaml settings.yaml` and edit
7. Copy `trade_logs/*.jsonl` from the backup folder if they exist
   (the source machine wrote them via `scripts/backup_trade_logs.ps1`)
8. Run `.venv\Scripts\python.exe -m scripts.smoke_phase4_step1` to verify
9. Start Claude Code in the project dir; point it at `CLAUDE.md` + this file

## Important invariants (do not violate)

- Compliance + risk gates run on **every** TradePlan. No workflow YAML can bypass them.
- Pattern detectors are pure functions of `(bars, config, as_of_ts)`. No `datetime.now()`.
- Broker credentials live only in `.env`. Never in `settings.yaml`, never in git.
- JSONL writes are append-only, one record per line, flush immediately.
- TradeRecord schema field names are frozen after first write.
- Live mode requires a HumanAckRecord within 15 minutes before any order ships to the broker.
