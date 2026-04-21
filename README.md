# TradeAgent

A multi-agent trading workflow manager for US equities and ETFs. Single-user
local FastAPI app that coordinates autonomous agents to screen stocks, generate
trade signals, plan trades, enforce compliance and risk rules, and route
approved plans to a broker. Reachable from mobile via Tailscale.

**Status:** Phases 1–3 complete · Phase 4 (Agents + Workflow Engine) in progress.
See [CLAUDE.md](CLAUDE.md) for the full roadmap and [HANDOFF.md](HANDOFF.md)
for a current-state catch-up.

## Stack

- **Backend:** FastAPI (async) · Pydantic v2 · Jinja2 · HTMX 2.0.4 · hand-rolled CSS
- **Data:** SQLite (session state) · JSONL (trade logs — the ML data pool) · YAML (configs)
- **Broker:** TradeStation API (paper + live) · research-mode stub adapter
- **Market data:** yfinance (bars) · Alpaca News (Benzinga-sourced) · SEC EDGAR (filings)
- **Transport:** Tailscale (mobile access) · ntfy (push notifications, Phase 6)
- **Python:** 3.14.4

## Architecture non-negotiables

- Mode switch — `research` / `paper` / `live` — gates every route and agent call.
- Compliance gates (C1–C8) and risk gates (R1–R9) run in-process on every TradePlan.
  No YAML workflow, route, or test can bypass them.
- Live mode requires a human approval (`HumanAckRecord`) within 15 minutes before
  any order ships to the broker. Enforced in the executioner, not the UI.
- Pattern detectors are pure functions of `(bars, config, as_of_ts)` — no wall
  clock, no live API calls. This is what enables Phase 5 backtesting to replay
  the same code over 10+ years of historical bars.
- Every completed trade writes a `TradeRecord` to JSONL. Schema field names are
  frozen after v1.0.

## Quick start (new machine)

```bash
git clone https://github.com/devguyjk/trading_app.git C:\Projects\TradingApp
cd C:\Projects\TradingApp
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
cp settings.example.yaml settings.yaml        # then edit
cp .env.example .env                          # then fill in secrets
.venv\Scripts\python.exe -X utf8 -m scripts.smoke_phase4_step1
```

The smoke test should print **`ALL GREEN — Phase 4 Steps 1-3 are wired up correctly.`**

## Project layout

```
services/       data_service, news_service, indicator_service, settings_service, log_service, broker_service
models/         Pydantic contracts (TradePlan, Signal, ComplianceVerdict, RiskVerdict, TradeRecord, ...)
brokers/        BrokerAdapter ABC + tradestation / historical / webull implementations
routers/        FastAPI routes (dashboard, pending, trades, settings, broker, stubs)
templates/      Jinja2 templates + HTMX partials
agents/         (Phase 4) universe_filter, analyst, portfolio_manager, compliance_officer, risk_manager
workflows/      (Phase 4) YAML workflow definitions — morning_run, evening_run, research_run
strategy_configs/   per-strategy pattern thresholds
universe_filters/   Finviz screener presets
scripts/        download_history, backup_trade_logs, smoke tests
data/           gitignored — bar cache, news cache, SQLite DB (all regenerable)
trade_logs/     gitignored JSONL — the ML data pool (back up via scripts/backup_trade_logs.ps1)
```

## License

Private — not for distribution.
