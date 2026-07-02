# TradeAgent — Project Context for Claude Code
**Last synced:** 2026-07-01 (re-baseline: `feat/strategy-research-pipeline` merged to
`main`. **`double_lock` + `swing_momentum` REMOVED**; the live layer is now the
video-mined, OOS-validated strategy suite + the strategy-research/optimization
pipeline + Kronos forecasting. Header rewritten to match the code — earlier "DL is
production" status was stale after the strategy swap.)

**Status:** The active strategy layer is the **video-mined strategy suite** (not
`double_lock`, which no longer exists). Five strategies are wired — config +
`workflows/<name>_scan.yaml` cron + the same compliance/risk gates — and marked
`active: true` on paper. `double_lock` (DL) and `swing_momentum` were deleted: DL's
*real* edge was ~53% WR (4-yr 30m replay, n=103, PF 1.21), not the n=17 82% figure,
so the project pivoted to strategies that hold up out-of-sample on ~20y of data.

### Live strategies — source of truth: `strategy_configs/*.yaml` + `strategies/strategy_docs/`
| Strategy | Type | Edge (OOS, net) | Core trigger |
|---|---|---|---|
| `momentum_breakout` (was S7) | daily trend | ~25% win / +0.45R | 126-day high breakout + volume confirm, SPY>200MA; 50-SMA trail (let winners run) |
| `fear_dip_reversion` (was S5) | daily mean-rev | ~32% win / +0.24R | ≥3×ATR below 50-SMA, targets the mean; only when SPY<200MA **or** VIX≥26 |
| `macd_run` | daily momentum | OOS PF ~1.52 / +0.27R | MACD line crosses up through signal below zero, 200-MA uptrend; exit on cross-back-down |
| `coil_breakout` | daily breakout | selective, high-quality | vol contraction (ATR10<ATR50) → expansion thrust breakout of 30-day range, uptrend |
| `fvg_continuation` | FX intraday | PF ~1.48 (OOS 1.46) | NY-session displacement Fair-Value-Gap, enter at market next bar, 3R / stop far gap edge / EOD |

Full rules + IS/OOS/control tables: `strategies/strategy_docs/S#_*.md` and
`STRATEGY_BACKTEST_REPORT.md`. Machine-readable results: `data/research/strategy_results/*.json`.
Recurring lesson from the rig: **edge is payoff geometry (cut at structure, let winners
run), not direction prediction.**

### Subsystems added in the pivot (beyond the pre-pivot app)
- **Strategy research/optimization**: `services/optimization_db.py`,
  `scripts/random_search.py`, `scripts/vector_analyze.py` (see the RESEARCH PIPELINE
  section below — still current).
- **Kronos forecasting**: `services/kronos_{service,pipeline,planner}.py`,
  `models/forecast.py` + pending-UI hook.
- **New routers**: `/data-fetch` (bulk OHLCV: HF parquet / yfinance / Alpaca),
  `/research`, and `manual_trade` (operator-driven entries through the gate flow).

> **NOTE (2026-07-01 re-sync):** any section below that presents `double_lock` /
> `wf_double_lock_1030` / `bellwether_16` as "the active strategy" is **HISTORICAL** —
> that layer was removed. It's kept for architectural context (agents, the two hard
> gates, workflow engine, broker layer, UI) which is unchanged and still governs the
> new strategies. The gate architecture (compliance C1–C8 global; risk R1–R9) applies
> to all five live strategies.

---

## DEFERRED TASK (2026-07-02) — FVG fidelity + conclusive intraday backtest

**Status: paused by operator; tooling built, data run pending on operator's machine.**

**Findings**
- `fvg_continuation` source = the **E3Mc "Displacement ORB + FVG"** video
  (`research/video_library/E3McKlAp3qk`). The creator executes on **5-minute**
  candles (15-min ORB → drop to 5m) on **GOLD (XAUUSD)** — *not* FX majors.
- The repo's validated version (PF 1.48 / OOS 1.46) is a **variant**: FX majors on
  **30m** — not the source instrument or timeframe.
- Logic confirmed with operator = **continuation** (enter at market when the FVG
  confirms and ride; do NOT wait for a return into the gap). ["A", 2026-07-02.]
- Quick yfinance stand-in (FX majors, ~2 months 2026-05-03→07-02): 30m PF 1.05 vs
  5m PF 0.91 — 5m added noise, but the sample is far too small + wrong instrument
  to conclude anything faithful.

**Already built (ready to run where an IB Gateway is up)**
- IBKR candle source with **paged/chunked history** (years) + **metal (XAUUSD)
  contract** support — `services/hf_data_service.py` (`_fetch_symbol_ibkr[_sync]`,
  `_ibkr_contract`, `_IBKR_CHUNK`).
- `scripts/fetch_fx_history.py` — pull years of FX + gold at 30m/5m via IBKR
  (paged → slow, ~1–2h for deep 5m; run once, overnight).
- `scripts/compare_fvg_intervals.py` — 30m-vs-5m (and FX-vs-gold) backtest on
  cached candles.
- `scripts/replay_fvg.py` parameterized by bar interval (30m stays default).

**Remaining (the task — on the operator's machine; the sandbox can't reach a local gateway)**
1. Gateway up → `python scripts/fetch_fx_history.py --start 2015-01-01 --intervals 30m,5m`
   (9 FX majors + XAUUSD).
2. `python scripts/compare_fvg_intervals.py --since 2015-01-01 --intervals 30m,5m`
   (and `--symbols XAUUSD` for the faithful gold run).
3. Decide: keep the validated 30m-FX variant, and/or adopt the faithful 5m-gold
   version if it holds OOS.
4. If adopting gold: confirm the `XAUUSD` CMDTY contract fetches cleanly; re-validate
   (control + OOS + breadth). Open follow-ups in `FVG_CONTINUATION.md` still apply.

---

## STRATEGY RESEARCH PIPELINE (added 2026-05-08 / 2026-05-09)

A parallel research subsystem next to the live trading code. Goal: find new
strategies that generalize beyond the bellwether-16 universe DL was tuned on.

### What was built
- **Data fetch page** (`/data-fetch`) — bulk OHLCV fetcher from 3 sources:
  - HF parquet (`paperswithbacktest/Stocks-Daily-Price`, daily, stocks)
  - yfinance (any symbol, multi-interval)
  - Alpaca historical bars (1d/1h/30m/15m/5m, ~5y intraday)
  - Saves to `data/historical/{SYM}_{interval}.csv` matching `data_service` format
  - Local HF parquet shards cached at `data/hf_cache/` (~488 MB) — bulk filtering
    is local + free, no rate limits

- **Optimization DB** (`services/optimization_db.py`, `data/optimization_results.db`):
  - `optimization_runs` — Phase C grid sweep (12k rows) with full params + scores
  - `param_reasoning` — per-param "why this value" text (auto-populated from
    each strategy's PARAMETER_SPEC)
  - `best_per_symbol` — winners per (strategy, symbol) with selection rationale
  - `random_search_trials` — Phase F: every random-sampled meta-strategy trial
    + IS/OOS scoring + symbol feature vector (12k rows so far)
  - `analysis_log` — scoped findings + warnings
  - `optimizer_checkpoints` — resume markers for the grid sweep

- **External strategy detectors** (`agents/detectors/external/`):
  - `bollinger_rsi_chartart`, `macd_sma200_chartart`, `pmax_explorer`,
    `supertrend_kivanc` — Pine→Python translations of TradingView strategies
    staged in `strategies/external/`
  - `meta_strategy.py` — universal parameterized detector covering 5 entry
    primitives × 3 regime filters × 3 stop types × 3 TP types
  - `_base.py` — shared `Signal` / `Trade` / `simulate_trades` / `summarize_trades`

- **Random search engine** (`scripts/random_search.py`) — samples meta-strategy
  configs uniformly, scores each on full / IS / OOS windows, persists every
  trial with feature vector. ~5 trials/sec, resumable, `--forever` mode for
  multi-day collection.

- **Vector analysis** (`scripts/vector_analyze.py`) — Spearman IC tables,
  categorical rankings, OOS-robust archetype clustering, archetype config
  cards. Output: `strategies/VECTOR_ANALYSIS.md`.

- **Synthesis report** (`scripts/synthesize_optimization.py`) — heat maps,
  primitive frequency, per-strategy summary. Output: `strategies/OPTIMIZATION_FINDINGS.md`.

### Validated findings (data, not opinion)
1. **DL real WR is ~53%, not 82%.** 4-yr replay over 2022-2026 on 30m bars
   gave 103 trades, 53.4% WR, PF 1.21 — modest edge, not a home run.
   The "82.4% WR" came from n=17. CLAUDE.md's older claim is updated here
   to set expectations correctly.
2. **PMax beats SuperTrend universally** when per-symbol-tuned (16/16
   bellwether symbols qualified at PF>1, median PF 2.16 vs SuperTrend 1.40).
3. **Author defaults from TradingView Pines are usually wrong** — ChartArt's
   `bb_length=200` loses on every bellwether-16 symbol; `bb_length=20`
   makes it a top performer on 5/16.
4. **Random-search top archetypes are heavily long-only** — 5/5 OOS-robust
   archetypes had `long_only=True` though it's only 30%-prior in the
   sampler (p ≈ 0.24% if random).
5. **All current research is on daily bars** — produces multi-week swing
   trades. Different bucket than DL (intraday). They're complementary.

### Universe screeners
- `bellwether_16` — original DL-validated 16 names (kept as-is)
- `high_atr_liquid` — 300 tickers, price>$10 / vol>2M / ATR>$3 USD (deprecated
  as of 2026-05-09; replaced by core_universe_100)
- `core_universe_100` (active research universe) — Two-stage:
  - **Stage 1 (Finviz, max_pages=50)**: cap=midover, US-listed, profitable,
    op margin pos, 5-yr EPS pos, current ratio>1, D/E<1, price>$15, vol>2M,
    P>SMA50 AND P>SMA200
  - **Stage 2 (local, fresh yfinance)**: ATR(14)/close ∈ [1.5%, 5%] AND
    P>SMA50 AND P>SMA200 (re-verified locally to fix Finviz staleness)
  - **Force-include list** in `scripts/build_core_universe_100.py::FORCE_INCLUDE`
    bypasses Stage 1 for known mega-caps that fail strict balance-sheet filters
    (e.g. AAPL D/E>1 from buybacks). Still subject to Stage 2 trend gate.
  - Current state: **44 names**, ~6 of Mag-7 in (META and MSFT correctly
    excluded for being below SMAs)

### price_action_pattern_recog_matrix (planned, not built)
Vector-similarity / kNN system for "find me past times the market state
looked like *this* and tell me what happened next." Different methodology
from random search:
- Per-bar state vector: RSI, MACD slope, ADX, %dist from VWAP, %dist from
  EMA20, range/ATR, rel-vol, candle sentiment
- Indices: FAISS in-memory + parquet metadata sidecar (NOT Pinecone — overkill)
- Bar interval: 15m AND 30m
- Storage: `agents/state_memory/`, `services/state_memory_service.py`,
  `data/state_memory/{faiss.index, metadata.parquet}`
- Designed to live alongside DL + random search, not replace them
- Spec lives in `strategies/RANDOM_SEARCH_DESIGN.md` (the meta-strategy
  spec) and the project plan in this CLAUDE.md section

### Companion documents (research)
- [strategies/STRATEGY_KNOWLEDGE.md] — primitive vocabulary, validated
  truths, per-strategy critique, composite proposals
- [strategies/OPTIMIZATION_FINDINGS.md] — heat maps + archetype clusters
- [strategies/VECTOR_ANALYSIS.md] — IC tables + OOS-robust top archetypes
- [strategies/CORE_UNIVERSE_100.md] — current universe snapshot
- [strategies/WORKFLOW.md] — end-to-end pipeline diagram + commands
- [strategies/RANDOM_SEARCH_DESIGN.md] — meta-strategy design space
- [HANDOFF.md] — what's running, what's next, where to pick up

### Quick command cheatsheet
```bash
# Refresh universe
python scripts/build_core_universe_100.py

# Bulk-fetch daily bars for a screener (skips already-cached)
python scripts/bulk_fetch_screener.py --screener core_universe_100 --source auto

# Long-running random search on the universe
python scripts/random_search.py --screener core_universe_100 --forever

# Reports (any time, even mid-run)
python scripts/report_random_search.py        # trial counts + top archetypes
python scripts/vector_analyze.py              # IC + clusters → MD report
python scripts/inspect_top_archetype.py       # re-run top 5 + dump trade ledger
```

---

> ⛔ **SUPERSEDED (2026-07-01).** The block below describes the pre-pivot state.
> `double_lock`, `bellwether_16`-as-active, and the DL auto-loop were **removed**.
> For the current live strategies see the header table above. Kept only as a record
> of the DL era and the "edge doesn't generalize" finding that motivated the pivot.

**Trading-app summary (live state as of 2026-05-07 — SUPERSEDED, see header):**
* **Strategy:** `double_lock` (intraday opening pattern; c1+c2 conviction at
  10:30 ET + regime gate VIX>=20, ADX<=35, RSI window). Backtest 87.5% WR /
  +5.18% on 16-name bellwether (Mar-Apr); 50% WR on 62 mega-caps;
  43.6% WR on 656 mid+caps — strategy edge does NOT generalize beyond the
  validated narrow universe. Active screener locked to `bellwether_16`.
* **Active broker:** Alpaca paper (100K Paper Acct). Live Trades account
  configured but inactive. Multi-account registry at
  `data/claude_trading_app.db::broker_accounts` + git-tracked YAML backup
  at `universe_screeners.yaml` and the broker analog (auto-export on every
  CRUD).
* **Auto-approve:** ON for `double_lock` on paper; HARD-BLOCKED for live
  (architectural — `auto_approve_service.safe_to_auto_approve` refuses
  live mode, regardless of strategy flag).
* **Guardrails:** `enhanced_live_safeguards: True` (extra "Are you sure?"
  prompts client-side in live mode); `earnings_blackout: 24h` actually
  wired via `services/earnings_service.py` (yfinance Ticker.calendar,
  4-hour TTL cache); `min_rr_ratio: 2.0` rejects swing plans with weak
  R:R; `human_ack_required: True` always on for live.
* **Position sizing:** `agents/portfolio_manager._compute_position_size`
  uses %-of-equity by default. Per-account override via
  `broker_accounts.extra_json.position_size_usd` (fixed $ per trade,
  ignores % calc). UI on `/broker` edit form. Hard caps: never > 5x %-calc
  shares, never > 95% of cash.
* **Manual controls:** Dashboard Close + TP buttons for any position
  (POST `/api/positions/{symbol}/{close,take-profit}`); trade-level edit
  (entry/stop/TP/deadline) at `/trades/{id}`. Each fires a tagged alert
  + ntfy push. Live mode adds confirmation prompt before the call.
* **Alerts:** 8 kinds — `lock1_scouted`, `armed`, `filled`, `closed`,
  `manual_take_profit`, `manual_edit`, `digest`, `rejected`, `test`.
  `rejected` is dashboard-only (no phone push) per `_NO_PUSH_KINDS`.
* **Daily digest:** new scheduler job at 16:30 ET Mon-Fri pushes ONE
  ntfy summary per weekday — even quiet days. Title format:
  *"Daily digest YYYY-MM-DD — N fired · M rejected · K filled"* or
  *"quiet day, 0 fires"*. Body lists per-workflow signal/plan counts,
  account state, and any errored runs.
* **Live status bar:** persistent strip atop every page (5s HTMX poll)
  showing equity / cash / day P&L + per-position chips with direction
  arrow, P&L $/% toggle, and TP/SL pills. Click any chip → live chart
  for that symbol.
* **History tab per strategy:** `/strategies/{name}/history` merges
  actual closed trades (JSONL) + simulated trades (replay engine) with
  dollar-emphasis summary (capital deployed, gross profit, gross loss,
  net P&L $, profit factor, return on risk). Capital input persists per
  browser; toggling instantly recomputes from cache without re-replay.
  "Ignore regime gate" research toggle for counterfactual analysis.
* **Multi-strategy comparison:** `scripts/replay_strategies.py` runs DL
  vs ORB vs VWAP-Reclaim side-by-side on the same universe + window.
  All share the 15:00 ET / 3% catastrophic-stop exit for parity.

**Known reliability properties:**
* **Single uvicorn worker** (`run.py prod` -> `--workers 1`) because
  the broker adapter is a per-process singleton; 2-worker setups
  diverge after any account-activation request.
* **Catch-up-on-restart:** scheduler.py `_catch_up_missed_runs` fires
  any missed `wf_*` or `dl_lock1_scout` job at startup if today's cron
  window has passed without a run — but only via a check-on-boot,
  NOT continuous. An app restart between 10:25-11:00 ET on weekdays
  may still catch up but at the wrong wall-clock entry price.
* **Adapter self-heal:** `broker_service.get_adapter_async()` checks
  the active slug in DB on every async accessor; if it diverges from
  the singleton's bound slug, rebuilds. Defends against multi-worker
  drift even though we default to 1 worker.
* **Smart bar refresh:** `services/data_service.refresh_if_stale`
  + per-(symbol, interval) tracker; the strategy-live page polls
  every 30s but the cache only refetches every 3 min during market
  hours, 30 min off-hours.

**Next chat options:** (a) ship the `manual buy` form (operator-driven
non-strategy entries with the same gate flow); (b) wire entry-fill
alerts (broker order-poll loop -> `filled` ntfy push currently
skipped); (c) add a continuous regime monitor + "regime change"
alert (currently regime is only checked at 10:00/10:30 ET); (d)
Phase 5 backtest engine UI + walk-forward optimization; (e) port
ORB-30m as a second autonomous strategy (data already shows it's
profitable on bellwether 16 at 47.7% WR / PF 1.11).

**Roadmap (current):**
- Phase 4 ✅ all sub-items
- DL-Filtered intraday strategy ✅ (detector + workflow + 15:00 ET close + auto-approve)
- Multi-account broker registry ✅ (paper + live, fixed-$ sizing per account)
- Manual position controls ✅ (close, TP, edit) + alerts
- Daily digest + rejected alerts ✅
- Modular dashboard ✅ (Portfolio/Market/News tabs, 5 widgets, ⚙ settings infra)
- Live status bar ✅ (top of every page, $/% toggle, TP/SL pills)
- Strategy History tab ✅ (per-strategy, dollar-emphasis, regime-ignore toggle)
- Multi-strategy comparison engine ✅ (DL vs ORB vs VWAP)
- Trade detail page ✅ (`/trades/{id}` unified, indicator picker, VADER news)
- Copy Insiders ✅ (House via ivanma9 API + Senate via eFD HTML parser)
- Stock Lists ✅ (10 defaults — S&P 500/400/600, NASDAQ-100, Dow 30, etc.)
- Earnings gate C7 ✅ (yfinance Ticker.calendar, 4h TTL cache)
- Screener registry persisted to git ✅ (auto-export on every CRUD; restore on boot)
- Phase 5 — Backtest Engine UI + walk-forward optimization (deferred)
- Phase 4.5 — Chart viewer sources + indicators (deferred)
- Phase 6 — entry-fill alert + mobile CSS pass + risk_manager postmortem
- Phase 7 — Memory, learning loop, polish
**Companion docs:**
  - `SKILL.md` (project root) — domain logic
  - `phase2_prompt.md` (project root) — UI design system + per-screen layouts (still authoritative for any UI work)
  - `phase4_prompt.md` (project root) — Phase 4 agents + workflow engine spec (revised 2026-04-20)
**Stack:** FastAPI · HTMX 2.0.4 · Jinja2 · hand-rolled CSS (dark theme) · SQLite · JSONL · Tailscale · ntfy · **Alpaca** (default paper) · TradeStation (live)
**Python:** 3.14.4 (moved off 3.12 on 2026-04-20 — the 3.12 install went missing and 3.14 wheels
resolved cleanly for pandas 3.0, numpy 2.4, alpaca-py 0.43, yfinance 1.3; no compat issues)
**Location:** `C:\Projects\Trading_app\` (local). Moved off Google Drive 2026-04-20 — Drive
sync + venv/SQLite was creating constant fsync churn. Cross-machine story: git clone for
code, `scripts/backup_trade_logs.ps1` for the ML data pool, one-time copy for `.env` secrets.

**Workflow preference (set 2026-04-22):** Claude edits directly in the repo root so
the user can test before any branching. Only when the user explicitly says "commit"
/ "push" / "branch" does Claude create a branch, commit, and push. Branch names
should be intuitive and tied to the feature (`feat/chart-indicators`,
`fix/select-dark-theme`) — not auto-generated adjective-scientist names.

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
│   │                              Auto-schedules `close_at_time()` after successful
│   │                              placement when `time_stop.active` (intraday DL exit
│   │                              at 15:00 ET via APScheduler one-shot date job).
│   └── detectors/               ← 9 swing detectors + 1 intraday detector
│       ├── __init__.py          ← ALL_DETECTORS (swing) + INTRADAY_DETECTORS (DL)
│       ├── _helpers.py          ← pivot_highs/lows, volume_ratio, wick helpers
│       ├── bull_flag.py
│       ├── inside_bar_nr7.py
│       ├── volatility_squeeze.py
│       ├── rsi_divergence.py
│       ├── vwap_reclaim.py
│       ├── double_bottom_top.py
│       ├── ascending_triangle.py
│       ├── cup_and_handle.py
│       ├── wyckoff_accumulation.py
│       └── double_lock_filtered.py  ← intraday opener; fires 10:30 ET only;
│                                      82% WR backtest (n=17, see HANDOFF.md);
│                                      separate INTRADAY_DETECTORS registry
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
│   ├── finviz_catalog.json      ← 76 usable Finviz filters (Elite-only stripped).
│   │                               Each entry: {id, label, tab, category, options[]}.
│   │                               Parsed once from Finviz HTML; committed to repo.
│   │
│   ├── analysis_service.py      ← Failure analysis data layer for /trades/analysis;
│   │                               auto-detects JSONL vs dump, production-filter toggle.
│   ├── dashboard_widgets.py     ← Modular Widget registry + base class. Each widget
│   │                               sets size/tab/refresh_seconds. Configurable via
│   │                               settings_schema → ⚙ icon → SQLite persistence.
│   ├── widget_settings.py       ← SQLite-backed get/set/reset for per-user widget
│   │                               overrides (table user_widget_settings).
│   ├── indicator_registry.py    ← Global IndicatorSpec catalog — single source for
│   │                               every indicator picker UI. Aligns with
│   │                               /api/indicators contract (sma20, vwap, rsi, atr…).
│   ├── probability_service.py   ← Backtest WR + live WR sample-size-weighted blend
│   │                               per strategy. Reads strategy YAML's backtest_summary
│   │                               and live trades from analysis_service.
│   ├── sentiment_service.py     ← VADER scoring (free) over NewsItems from
│   │                               news_service. Returns SentimentScore + aggregate.
│   ├── trade_lookup.py          ← Unified "trade by id" — abstracts pending_approvals
│   │                               (SQLite) + trade_logs/*.jsonl. Returns TradeView.
│   └── scheduler.py             ← APScheduler — auto-globs workflows/*.yaml and
│                                   registers cron jobs from each `schedule:` field.
│                                   Capitol Trades polling. (Shipped in main 70ccbe6.)
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

### Copy Insiders + Stock Lists routes (added 2026-04-25 PM)
```
GET  /copy-trading                 → 307 redirect → /copy-insiders/rankings
GET  /copy-insiders                → 307 redirect → /copy-insiders/rankings
GET  /copy-insiders/rankings       → leaderboard + multi-follow + composite rank
GET  /copy-insiders/trades         → multi-select politicians, view disclosures, ticker hover-chart
GET  /universe/stock-lists         → 10 default ticker lists (cards)
GET  /universe/stock-lists/{slug}  → ticker grid + filter + copy-all + Finviz links

GET  /api/copy-trading/all-members        → House (ivanma9) + Senate (eFD cache), composite rank, last_refresh
POST /api/copy-trading/follow             → add politician to followed_politicians; auto-fires perf compute background task
DELETE /api/copy-trading/follow/{slug}    → unfollow
PATCH  /api/copy-trading/follow/{slug}    → toggle enabled
PATCH  /api/copy-trading/favorite/{slug}  → pin to top of followed list
GET  /api/copy-trading/followed           → JSON list
GET  /api/copy-trading/disclosures?slugs=…  → multi-politician disclosure feed
POST /api/copy-trading/performance/{slug}   → compute win-rate / 30-day return; chamber-aware dispatch
POST /api/copy-trading/compute-all-performance  → bulk compute House + Senate
POST /api/copy-trading/refresh-senate     → scrape efdsearch.senate.gov, cache filings
POST /api/copy-trading/parse-senator/{slug} → parse all PTR HTML tables, cache trades, compute perf
GET  /api/copy-trading/politicians        → House leaderboard (cached in copy_trading_config)
POST /api/copy-trading/scan               → manual Capitol Trades poll (now uses ivanma9)
GET  /api/copy-trading/queue              → recent disclosure rows from politician_trades

GET  /api/stock-lists                     → all lists (seeds defaults if empty)
GET  /api/stock-lists/{slug}              → one list with full ticker array
POST /api/stock-lists/{slug}/refresh      → re-fetch from source (Wikipedia for index lists)
POST /api/stock-lists/refresh-all         → refresh all dynamic lists
```

---

## Copy Insiders subsystem (added 2026-04-25 PM)

### Data sources
- **House** — `congressional-trading-datastore-production-9fd6.up.railway.app`
  (the `ivanma9/CongressionalTrading` open-source REST API). Replaced the dead
  `api.capitoltrades.com` (which now NXDOMAIN's). 24,492 trades, daily-refreshed
  at the source. Free, no auth.
- **Senate** — `efdsearch.senate.gov/search/`. No public API; we accept the
  prohibition agreement once per session, hit `/search/report/data/` for the
  PTR list, then fetch each `/search/view/ptr/{ptr_id}/` page (which renders
  trades as **structured HTML tables, not PDFs** — no PDF parser needed).

### Performance metric (the "trading success" measure)
The hosted ivanma9 `/performance` endpoint exists but always returns 0 trades —
broken on their side. We compute locally with **yfinance** in
`services/capitol_trades_service.py::_compute_performance_locally`:
1. For each trade with a ticker, fetch the close price on disclosure date and 30 days later
2. Win = price moved the same direction as the trade (up for buy, down for sell)
3. Aggregate: `win_rate_30d`, `avg_return_30d`, `avg_spy_return_30d` (benchmark)
4. Senators reuse the exact same function via shape adaptation in
   `services/senate_efd_service.py::compute_senator_performance`

### Composite rank (1-10) for the dropdown
Computed in `routers/copy_trading.py::_compute_composite_ranks`:
- Inputs: `trade_count_90d` (0.25 weight), `win_rate_30d` (0.40), `avg_return_30d` (0.35)
- Each metric percentile-ranked across the cohort of members with cached perf
- Weighted sum binned into deciles 1-10
- Dropdown options colored 🔴 (1-5 below avg) or 🟢 (6-10 above avg)

### DB tables (all owned by `services/db_service.py`)
- `followed_politicians` — multi-follow with per-row enabled toggle, favorite pin,
  cached perf metrics
- `member_performance_cache` — keyed perf metrics for any politician (followed or not)
- `senate_filings` — eFD PTR filing index (used for diff detection on next refresh)
- `senate_trades` — individual rows parsed from PTR HTML tables `(ptr_id, row_num)` PK
- `politician_trades` — pre-existing; legacy Capitol Trades feed
- `copy_trading_config` — k/v store; now holds `latest_rankings_json`,
  `latest_rankings_at`, `senate_last_refresh_at`

### Stock Lists subsystem
- `services/stock_lists_service.py` — 10 default lists in `_DEFAULTS`. Two
  source types: `wikipedia` (S&P 500/400/600, NASDAQ-100, Dow 30 — refreshable
  via `pd.read_html`) and `static` (Mag 7, FAANG, sector ETFs, etc.).
- Wikipedia scraping requires a descriptive User-Agent or returns 403.
- Routes registered BEFORE `universe.router` in `app.py` so
  `/universe/stock-lists` doesn't get shadowed by `/universe/{preset_name}`.

### Sidebar accordion
- `templates/base.html` rewrote nav into parent/child groups with chevron toggles
- `static/app.css` `.nav-group / .nav-parent / .nav-children / .nav-child` block
- Open state persists in `localStorage['sidebar.openGroups']`
- Active child auto-expands its parent

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

**Phase 4 polish — Stock Screener UX pass (2026-04-22 afternoon):**
- ✅ UI-only rename "Preset" → "Stock Screener" everywhere user-visible.
  URLs, DB tables, Python fn names unchanged (still `preset`/`universe` on the
  code side). Semantically clean: a **screener** is the filter recipe; a
  **universe** is its output ticker list.
- ✅ Description field: `<input>` → 3-row `<textarea>` (resizable vertically).
- ✅ Notes field surfaced in UI: new 5-row textarea on create + edit forms.
  DB column `universe_presets.notes` + router already supported it — this was
  pure UI wiring.
- ✅ Filter picker (+ Add filter modal) restructured: two-level header (tab
  in uppercase gray with border; category in accent-blue with left stripe).
  Items indented 32px under their category. Explicit alphabetic sort at all
  3 levels (tabs, categories, filters).
- ✅ Scrape cap: `scrape_finviz_filters` max_pages 5 → 15 (= 300 tickers).
  Return signature changed to `(tickers, truncated: bool)` — truncated=True
  when max_pages hit with last page still full. API exposes `truncated` +
  `max_results: 300`. UI surfaces a **bold red banner + red toast + red `300+`
  count** when truncated, so the user knows the filter isn't restrictive enough.
- ✅ Dark-theme fix for `<select>`: `color-scheme: dark` on `:root` (global —
  covers every form control in the app); `.filter-select` gets `appearance: none`
  + inline SVG chevron + explicit `option` bg/color. Fixes Windows Chrome/Edge
  rendering native selects with OS-default white.
- ✅ `runTest()` auto-saves before scraping (`savePreset({silent:true})`).
  No more "I tweaked filters and ▶ Run returned stale results".
- ✅ Chart viewer on /universe edit page: every ticker in "Saved universe" +
  test-run results is now a clickable `.ticker-chip`. Click → timeframe
  popover (1H/2H/4H/1D, positioned adaptively) → floating `.chart-panel`:
  draggable by titlebar, resizable via bottom-right grip (ResizeObserver
  rescales the chart), pinnable (accent-blue border toggle), closable,
  multiple panels allowed (each click spawns a new offset panel). Uses
  existing `/api/bars/{symbol}` + Lightweight Charts 4.1.3 from CDN.

### Phase 4.5 — Chart sources + indicators (NEXT SESSION — see HANDOFF.md for full plan)

Continuous push planned across two sub-sessions. Four chart-source options
per ticker (Quick · Finviz image · TradingView widget · Open in Finviz ↗),
a new `GET /api/indicators/{symbol}` endpoint wrapping `services/indicator_service.py`,
shared `static/chart_tools.js` consumed by both `/universe/{name}/edit` and
`/pending`, filter-aware auto-activation (screener's `filters` dict → overlay
indicators turned on), toggle chips in chart panel header with localStorage
persistence. Overlays first (SMA/BB/high-low bands), then sub-panes
(RSI/MACD/ATR/Volume). Indicator math stays server-side in
`services/indicator_service.py` — single source of truth for both agents
and chart UI.

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

## Opening Candle Research (completed 2026-04-24)

Ad-hoc research session — not part of the trading app's agent pipeline. Scripts live in
`scripts/` and are standalone (yfinance data, no app dependencies).

### Scripts
| File | Purpose |
|---|---|
| `scripts/test_opening_candle_theory.py` | Tests the reversal theory: first 15-min bearish candle → bullish day. Result: **33.1% accuracy** — theory disproven. |
| `scripts/scan_opening_patterns.py` | Exhaustive pattern scanner: all 1–3 candle combos at 15M + 30M with volume dimension. Outputs ranked patterns sorted by z-score. |
| `cmds.py` | Runner shim — currently points to `scan_opening_patterns.py`. Overwrite to switch scripts. |

### Key findings
- **Continuation, not reversal.** The 15-min first candle predicts continuation (~67%), not reversal.
- **30-min candle encodes better signal.** 4 binary dimensions per candle: direction (BULL/BEAR), body strength ≥50% range (STR/WK), buy pressure ≥60% close-in-range (HPRS/LPRS), volume vs slot 20-day median (HVOL/LVOL).
- **Slot-specific volume average** — rolling 20-bar average of just the 9:30 bar, not diluted by other session bars.
- **Top single-candle patterns:** `BULL.STR.HPRS.HVOL` and `BEAR.STR.LPRS.HVOL` on the 30M first candle predict day direction with 83–85% accuracy (OOS: 86–90%).
- **Double-lock patterns:** Two consecutive same-direction conviction candles → 97–98% directional accuracy in-sample, 94–97% OOS. This is the statistical anchor for Strategy 2.
- **134 significant patterns** (z≥2.0, n≥15) found across all symbols; 84 with z≥3.0.

### Pine Script strategies (`scripts/pine/`)
Both Pine Script v6 files committed. Run in TradingView Pine Editor → Add to chart → Strategy Tester.

| File | Strategy | Entry | Exit | Notes |
|---|---|---|---|---|
| `strategy1_FHC.pine` | First Hour Conviction (FHC-S1) | 10:00 AM (1st 30M candle close), HVOL required, SPY filter | 2:1 R:R TP/SL, EOD backup | Backtested: SPY 49% WR PF 1.19 / NVDA 50% WR PF 1.11 — too weak |
| `strategy2_DL.pine` | Double Lock (DL-S2) | 10:30 AM (2nd consecutive conviction candle close) | EOD 3PM only, 3% catastrophic stop | Fixes FHC-S1 mismatch: no TP target matches what scanner validated. **Not yet backtested.** |

### Why Strategy 1 failed (and how Strategy 2 fixes it)
The scanner measured *day-close direction* relative to day-open price. Strategy 1 tested *intraday TP/SL hit* using a 0.5–0.8% SL, but avg MAE was 1.4–1.8%, so stops fired on winning-direction days. Strategy 2 removes the TP entirely and exits at EOD close — the mechanic now matches exactly what was validated.

### Next step for Pine Script work
Run Strategy 2 (DL-S2) on SPY and NVDA on a 30-min chart (Jan 2024–present) and report Strategy Tester metrics (win rate, profit factor, max drawdown, total trades). If ≥72% win rate, write Strategy 3: Failed Follow-Through Reversal.

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
