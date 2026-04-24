# Session Handoff — 2026-04-24

Short catch-up doc for resuming in a fresh Claude Code session.
Read order: **CLAUDE.md** first (full spec + conventions), then this file.

---

## Current state

**Phases 1–4 substantially complete.**
One Phase 4 item remains: `services/scheduler.py` (APScheduler).
Phase 5 (Backtest Engine) is queued. **Next chat should do the Phase 4.5 chart-viewer
+ indicators push** (detailed further below), unless the user wants to continue the
opening candle Pine Script work first.

---

## What shipped this session (2026-04-24) — Opening Candle Research

Standalone research session — no changes to the FastAPI app. All scripts are
independent (yfinance data only, no app dependencies).

### Theory disproven — continuation is the signal
- Wrote and ran `scripts/test_opening_candle_theory.py` — reversal theory (first 15-min
  bearish candle → bullish day) tested across all symbols with 1d CSVs.
- **Result:** 33.1% theory accuracy, 28.9% trade win rate. Theory fails badly.
- Real finding: continuation is the dominant signal (~67%).

### Pattern scanner — 134 significant patterns found
- Wrote and ran `scripts/scan_opening_patterns.py` — exhaustive 1–3 candle combos at
  15M and 30M. 4 dimensions per candle: direction, body strength, buy/sell pressure,
  volume vs slot-specific 20-day median.
- **134 patterns** with z≥2.0 (n≥15). **84** with z≥3.0.
- Top single-candle: `BULL.STR.HPRS.HVOL` and `BEAR.STR.LPRS.HVOL` at 30M → 83–85%
  directional accuracy (OOS: 86–90%).
- Double-lock (two consecutive conviction candles same direction) → **97–98% in-sample,
  94–97% OOS**. This is the statistical anchor for Strategy 2.

### Two Pine Script v6 strategies written and saved
| File | Strategy | Entry | Primary exit | Status |
|---|---|---|---|---|
| `scripts/pine/strategy1_FHC.pine` | First Hour Conviction | 10:00 AM close, HVOL, SPY filter | 2:1 R:R TP/SL | **Tested: SPY 49% WR, NVDA 50% WR — too weak** |
| `scripts/pine/strategy2_DL.pine` | Double Lock | 10:30 AM close (2nd consecutive candle) | EOD 3PM, 3% cata stop | **NOT YET TESTED — run this next** |

### Why FHC-S1 failed
Scanner validated *day-close direction*. FHC-S1 tested *intraday TP hit* with a
0.5–0.8% SL. The avg MAE was 1.4–1.8%, so stops fired on winning-direction days.
DL-S2 removes the TP and exits at EOD — the mechanic now matches what was validated.

### Files added this session
```
A  scripts/test_opening_candle_theory.py
A  scripts/scan_opening_patterns.py
M  cmds.py                              (now points to scan_opening_patterns.py)
A  scripts/pine/strategy1_FHC.pine
A  scripts/pine/strategy2_DL.pine
```

---

## Immediate next tasks for new session

1. **Run DL-S2 Pine Script** on SPY and NVDA (30-min chart, Jan 2024–present).
   Open TradingView → Pine Editor → paste `scripts/pine/strategy2_DL.pine` → Save →
   Add to chart → Strategy Tester tab → report: win rate, profit factor, max drawdown,
   total trades.
2. **If DL-S2 ≥ 72% win rate** → write Strategy 3 (Failed Follow-Through Reversal)
   in Pine Script v6.
3. **Phase 4.5 chart viewer + indicators push** — see plan below.

---

## What shipped the prior session (2026-04-22 afternoon)

A continuous UX pass on the Stock Screener page (formerly "Preset" — see rename).

### Renames — "Preset" → "Stock Screener" (UI-only)
- All user-visible copy renamed: page title, breadcrumbs, buttons, toasts, confirmations.
  "Universe presets" → "Stock screeners"; "+ New preset" → "+ New screener";
  "Preset info" card → "Screener info"; etc.
- **URLs unchanged** (`/universe/*`), **DB tables unchanged** (`universe_presets`),
  **Python fn names unchanged** (`get_preset_db`, etc.). The code side still
  speaks "preset"; the UI speaks "screener". Semantically this works well:
  a **screener** is the filter recipe; a **universe** is its output ticker list.
- If you want the full rename later (DB migration + URL migration + fn rename),
  that's a separate ~1–2 hr job. For now UI-only is intentional.

### Description + Notes fields
- `Description`: single-line `<input>` → 3-row `<textarea>` (resizable vertically).
- `Notes`: new 5-row textarea under Description. DB column already existed in
  `universe_presets.notes` + router already accepted the field — this session
  just surfaced it in the UI.
- Both wired into the create form (new-screener flow) and update form
  (edit flow). `savePreset()` now includes `notes`; `cf-notes` in create-form.

### Filter picker ("+ Add filter" modal)
- Two-level hierarchy rendered with distinct styling:
  - **Tab header** (Descriptive / Fundamental / Technical) — uppercase, spaced,
    tertiary gray, border-separated.
  - **Category header** (Valuation / Moving Averages / …) — accent-blue text on
    blue tint with a left accent bar.
- Items indented 32px under their category.
- Explicit `.sort(localeCompare)` at all 3 levels — tabs, categories, filters.
  Catalog was mostly sorted already but it's now enforced in JS so a future
  re-scrape can't break ordering.
- Empty tabs stay hidden when a search query kills every child.

### Scrape behavior — 300 cap + truncation warning
- Finviz scrape `max_pages` bumped from 5 → 15 (× 20 rows/page = 300).
- `scrape_finviz_filters()` now returns `(tickers, truncated: bool)`.
  `truncated=True` when we stop because we hit `max_pages` with the last page
  still full (i.e. more results exist beyond the cap).
- API response shape: `{count, tickers, truncated, max_results}`.
- UI when truncated=true:
  - **Bold red banner**: ⚠ RESULT LIMIT HIT (300) — filter is NOT restrictive enough.
  - Ticker count renders in red with `+` suffix (e.g. `300+`).
  - Red toast: "Limit hit (300+) — tighten filters".

### Dark theme — select dropdowns
- Root fix: `color-scheme: dark` on `:root` in `static/app.css`.
  Tells Chromium to use dark form widgets globally — covers all `<select>` and
  form controls across the app, not just this page.
- `.filter-select` also gets `appearance: none` + inline SVG chevron for a
  custom closed-state look. Explicit `.filter-select option` bg + color for
  the dropdown list items.
- Fixes the original Windows Chrome/Edge issue where native `<select>`s
  ignored CSS `background` and rendered in OS white.

### Auto-save before ▶ Run
- `runTest()` now calls `savePreset({silent: true})` before scraping.
- The Finviz scrape reads from SQLite, so this keeps scrape and form state
  in sync — no more "I edited filters, clicked Run, and got old results".
- `savePreset()` grew a `{silent: true}` option that returns a bool so
  callers can chain.

### Chart viewer (NEW — drag+resize+pin all done)
Every ticker in the "Saved universe" card + test-run result list is now a
clickable `.ticker-chip`. Click flow:

1. Chip click → timeframe popover (1H / 2H / 4H / 1D), positioned adaptively
   near the chip (flips above chip if overflow bottom).
2. Pick timeframe → floating `.chart-panel`:
   - **Draggable** by titlebar (mousedown/move/up handlers).
   - **Resizable** via bottom-right grip — chart rescales via `ResizeObserver`.
   - **Pinnable** (📌 toggles accent-blue border; semantic hook for future
     "don't auto-close" logic).
   - **Closable** (× in titlebar).
   - **Multiple panels allowed** — each click spawns a new one, offset from
     the last (cycles through 6 offset slots).
   - Cleanup via `MutationObserver` — when panel is removed, chart disposed
     and ResizeObserver disconnected.
- Uses existing `GET /api/bars/{symbol}?interval=&limit=` endpoint.
- Lightweight Charts 4.1.3 loaded from unpkg CDN (same as `/pending`).

---

## Files changed this session

```
M  routers/universe.py         # max_pages 5→15, truncated in response
M  services/universe_service.py # scrape returns (tickers, truncated)
M  static/app.css              # color-scheme: dark
M  templates/universe.html     # rename Preset→Screener
M  templates/universe_edit.html # everything else — rename, notes, chart viewer, picker groups, dark-select, auto-save
```

No DB migration, no new routes, no new Python files.

---

## Next session plan — chart viewer + indicators (continuous push)

The user wants this done in ONE chat. Estimated **~5 hours total**.
Split into two sequential sessions for tracking:

### Session 1 (~2.5 hrs) — chart sources + overlay indicators

**Goal:** Four chart-source options per ticker + filter-aware auto-activated
overlay indicators.

1. **4 chart sources in the ticker popover:**
   - **Quick chart** — existing in-app Lightweight Charts panel (what ships
     today — fast, minimal, needs DIY indicators).
   - **Finviz chart image** — `<img src="https://finviz.com/chart.ashx?t=X&ta=1&p=d">`.
     Static PNG. Comes with SMA 20/50/200 + RSI + MACD overlays **baked in**
     when `ta=1` is passed. No JS required. Timeframe param: `p=d|w|m` for
     daily/weekly/monthly (intraday needs Elite).
   - **TradingView widget** — `<iframe>` of the free TV Widget at
     `https://www.tradingview.com/widgetembed/?symbol=X&interval=D&theme=dark`.
     100+ indicators, drawing tools, all in-iframe. **No datafeed adapter
     needed** — TV supplies the data. Free, TV-branded. This is the "pay-
     nothing TradingView" option (distinct from the TV Charting Library
     which would need our own datafeed).
   - **Open in Finviz →** — external link to `https://finviz.com/quote.ashx?t=X`
     in a new tab. Can't iframe it (Finviz sends `X-Frame-Options: SAMEORIGIN`)
     but it's the full fundamentals+news drilldown view.

2. **New endpoint:** `GET /api/indicators/{symbol}?interval=&indicators=sma20,sma50,...`
   Wraps `services/indicator_service.py` (23 hand-rolled indicators already
   exist). Single source of truth — the agents and the chart consume the
   exact same math. Response format: `{indicators: {sma20: [...], sma50: [...]}, timestamps: [...]}`.

3. **New shared file:** `static/chart_tools.js`
   - `createChartPanel(symbol, interval, opts)` — extracted from
     `universe_edit.html` so `/pending` can reuse it.
   - `renderOverlay(chart, {type, period, color})` — draws overlay line series.
   - Compute fallbacks (SMA, EMA, BB) for when server endpoint unavailable.

4. **Overlay indicators wired:**
   - SMA(20), SMA(50), SMA(200) — the three periods most commonly filtered on.
   - Bollinger Bands (20, 2σ) — upper/middle/lower lines.
   - High/Low bands (20d, 50d, 52w) — two horizontal lines per period.

5. **Filter-aware auto-activation.** When a chart panel opens for a ticker
   belonging to a given screener, read the screener's `filters` dict and
   auto-toggle matching overlays. Mapping:

   | Filter param | Auto-shown |
   |---|---|
   | `ta_sma20` | SMA(20) |
   | `ta_sma50` | SMA(50) |
   | `ta_sma200` | SMA(200) |
   | `ta_highlow20d` | 20-day high+low bands |
   | `ta_highlow50d` | 50-day high+low bands |
   | `ta_highlow52w` | 52-week high+low bands |

6. **Toggle chip UI** in chart panel header — small chips the user can click
   on/off: `SMA20 · SMA50 · SMA200 · BB · H/L20 · H/L50 · H/L52w`.
   Filter-activated ones start pre-selected; others start off.

7. **Persist per-user toggle preferences** in `localStorage` keyed by a
   sensible key (e.g. `chart.indicators.universe_edit`). Next chart open
   remembers what the user had on.

### Session 2 (~2.5 hrs) — sub-pane indicators + /pending rollout

**Goal:** RSI/MACD/ATR/Volume in a sub-pane below the price chart; ship
the shared chart_tools.js into `/pending` too.

1. **Sub-pane scaffolding:**
   - Second `LightweightCharts.createChart()` instance below the main chart.
   - Synced time-scale: when one chart scrolls/zooms, the other follows.
     Use `subscribeVisibleTimeRangeChange` on each, apply range to the other
     with a mutex to avoid feedback loops.
   - Layout split: main chart 70% of panel height, sub-pane 30%, with a
     ~4px resizable splitter.

2. **Sub-pane indicators:**
   - RSI(14) — line series with 30/70 horizontal threshold lines.
   - ATR(14) — line series.
   - MACD(12, 26, 9) — MACD line, signal line, histogram.
   - Volume — histogram, green/red based on up/down candle.

3. **Auto-activation additions:** `ta_rsi` set → RSI on;
   `ta_averagetruerange` set → ATR on.

4. **Roll out to `/pending`:**
   - Import `chart_tools.js` on `/pending`.
   - Replace `/pending`'s inline chart creation with the shared helper.
   - Each of the two existing `/pending` panes gets the same toggle chips +
     filter-aware auto-activation (based on the plan's screener context).
   - Verify crosshair sync and lazy-load behavior still work.

5. **Polish:**
   - Keyboard shortcuts in panel: `Esc` close, `1/2/4/D` switch timeframe.
   - Indicator color scheme pinned in CSS variables so it's consistent
     across every chart panel.

### Files that will change

**New:**
- `static/chart_tools.js` — shared chart helper (panel creation + render
  helpers + compute fallback).
- `routers/indicators.py` — `GET /api/indicators/{symbol}` endpoint.

**Modified:**
- `templates/universe_edit.html` — extract chart creation, add source picker
  (4 buttons), add toggle chips, wire filter-aware auto-activation.
- `templates/pending.html` — use shared helper, add toggle chips.
- `app.py` — mount indicators router.

### Invariants the plan respects

- `services/indicator_service.py` stays the authority on indicator math.
  Any new JS compute is only a fallback for when the server call hasn't
  completed yet — final values always come from the server.
- Pure-function-of-bars property is preserved: indicator math is
  deterministic given the bar series, so the same `as_of_ts` replay
  property that Phase 5 needs continues to hold.
- No third-party JS beyond Lightweight Charts (already on CDN) + the
  TradingView Widget iframe (zero code, it's just an `<iframe>`).

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
- `BROKER_PROVIDER=alpaca` (default). `BROKER_PROVIDER=tradestation` to opt in.
- Env vars: `ALPACA_API_KEY` + `ALPACA_API_SECRET`.

### Executioner (brought forward from Phase 6)
- `agents/executioner.py` — gate re-check + HumanAckRecord freshness (15 min)
  → `BrokerAdapter.place_order()`. Research mode refuses all orders.
- `routers/pending.py` — approve path wired: HumanAckRecord → executioner → SQLite.

### /pending dual charts
- Dual Lightweight Charts (replaced TradingView iframe). Crosshair sync.
  Lazy-load older bars (300/page, `?before=<epoch>`). Plan levels as
  labeled horizontal price-lines. Filter tabs; gate badge icons; approve
  disabled after 15-min expiry.

### Universe Preset Manager (now "Stock Screener")
- SQLite-backed CRUD for named screeners. Each has title+slug+description+
  notes+filters dict+output_tags+tickers.
- `services/finviz_catalog.json` — 76 usable Finviz filters (Elite-only
  stripped). Committed; not re-scraped at runtime.
- `universe_filter_config.yaml` — 14 default-visible filter IDs.
- `agents/universe_filter.py` SQLite-first: tries DB before YAML fallback.
- `/run-agent` endpoint runs in-process prescreen on saved tickers and
  returns ranked shortlist.

---

## Remaining Phase 4 item (deferred)

`services/scheduler.py` — APScheduler that reads each workflow's `schedule:`
cron field and fires the pipeline automatically. Build this or skip to
Phase 5 and return.

---

## Bootstrap on a new machine

1. `git clone <repo_url> C:\Projects\Trading_app`
2. `cd C:\Projects\Trading_app`
3. `python -m venv .venv && .venv\Scripts\pip install -r requirements.txt`
4. Copy `.env` from password manager (see `.env.example`):
   - `ALPACA_API_KEY` + `ALPACA_API_SECRET` — required for paper trading
   - `BROKER_PROVIDER=alpaca` (or `tradestation`)
5. `cp settings.example.yaml settings.yaml` and edit
6. Copy `trade_logs/*.jsonl` from backup if available
7. `python run.py dev` — server at http://localhost:5000

---

## Workflow preference — changes-first-in-root, then branch on signal

Going forward (new preference set this session):
- Claude edits directly in the repo root (`C:\Projects\Trading_app\`) for
  a given feature, so the user can test immediately without switching
  branches.
- Only when user says "commit" / "push" / "branch" does Claude create a
  branch, commit, and push.
- Branch names should be intuitive and tied to the feature, e.g.
  `feat/chart-indicators`, `fix/select-dark-theme`, not the auto-generated
  adjective-scientist names.

This HANDOFF session was produced from a worktree at
`.claude/worktrees/sweet-brahmagupta-28af7a/` for legacy reasons; the
next session should work directly in the main repo.

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
  (Note: the /universe chart viewer uses the TV *Widget* as one of four source options,
  which is different from the TV Charting Library that `/pending` originally used.)
- Do NOT re-scrape `finviz_catalog.json` at runtime — it's a committed static file.
- Do NOT re-define `--surface-1/2/3` or `--font-mono` in page templates —
  they live in `static/app.css` `:root` block.
- `services/indicator_service.py` is the single source of truth for indicator
  math. Any client-side compute is fallback only.
