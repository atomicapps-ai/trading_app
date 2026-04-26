# Session Handoff — 2026-04-25 (afternoon: Copy Insiders + Senate + Stock Lists)

Short catch-up doc for resuming in a fresh Claude Code session.
Read order: **CLAUDE.md** first (full spec + conventions), then this file.

---

## What shipped this session (2026-04-25 PM)

### TL;DR
Copy Trading was rebuilt as **Copy Insiders** with both chambers, multi-follow,
working data sources, real performance metrics, persistent state, and a
sidebar-accordion redesign. Plus a new **Stock Lists** submenu with 10
pre-loaded ticker collections.

### Root-cause fix: Capitol Trades API was dead
- `api.capitoltrades.com` no longer resolves (NXDOMAIN). The original
  scraper was failing silently and returning 0 trades.
- Replaced with the working hosted API at
  `congressional-trading-datastore-production-9fd6.up.railway.app`
  (open-source `ivanma9/CongressionalTrading` project; 24,492 trades,
  daily-refreshed, free, no auth).
- Hosted `/performance` endpoint exists but is broken (always returns
  `total_trades: 0`). We compute locally with **yfinance** instead — same
  win-rate / 30-day return / SPY benchmark methodology.

### Senate via efdsearch.senate.gov
- New `services/senate_efd_service.py` wraps the eFD search flow:
  GET `/search/home/` → POST agreement → POST `/search/report/data/` → JSON list
- **Critical discovery**: Senate PTRs are served as **structured HTML
  tables**, not PDFs. No PDF library required — BeautifulSoup over the
  `<table>` extracts trades cleanly.
- New `senate_filings` table caches the PTR index (used for diff
  detection). New `senate_trades` table caches individual transactions
  parsed from each PTR (`(ptr_id, row_num)` PK).
- `compute_senator_performance(slug, name)` adapts Senate trade rows to
  the `PoliticianTrade` shape and feeds them through the same yfinance
  pipeline used for House members. **Verified: Boozman = 64.1% win,
  +1.88% avg 30d return, +2.35% alpha vs SPY (n=64 trades, 6 PTRs)**.

### Composite ranking 1-10
- `routers/copy_trading.py::_compute_composite_ranks` — for the dropdown
- Inputs: `trade_count_90d` (0.25), `win_rate_30d` (0.40), `avg_return_30d` (0.35)
- Each metric percentile-ranked across the cached cohort, weighted, binned
  into deciles. Dropdown options colored 🔴 (1-5) / 🟢 (6-10).

### UX changes
- **Sidebar accordion**: Copy Trading → "Copy Insiders" parent group with
  children Politician Rankings + Politician Trades. Universe parent group
  with children Stock Screeners + Stock Lists. Open state persists in
  localStorage. `templates/base.html` + `static/app.css` `.nav-group/.nav-child`.
- **Persistent rankings cache**: `/api/copy-trading/politicians` writes the
  result to `copy_trading_config.latest_rankings_json` so the leaderboard
  re-renders on app restart without a manual click. "Loaded 5m ago"
  timestamp shown next to Reload button (with absolute local time on hover).
- **Pin to top** (favorites): `is_favorite` column on `followed_politicians`,
  amber row tint, ⭐ button.
- **Auto-compute on follow**: FastAPI `BackgroundTasks` kicks off the
  yfinance computation when a politician is followed, so the row populates
  within ~30s without a manual ↻ click. Chamber-aware dispatch routes
  senators through the eFD pipeline.
- **"No equity trades"** state: when `perf_trade_count == 0` after compute,
  the followed-list row shows the explanation instead of blank dashes.
  This catches cases like Cisneros (mostly bonds) and McCormick (54/55
  trades non-equity).
- **Senate stale banner**: amber banner above the dropdown when Senate
  data is > 7 days old (`senate_last_refresh_at` config key).

### Politician Trades page (`/copy-insiders/trades`)
- Multi-select checkboxes with filter input
- URL deep-link `?politicians=slug1,slug2`
- Combined disclosure table sorted by trade date
- **Ticker hover** → 250ms debounced floating chart popover (120 daily
  bars from `/api/bars/{symbol}`, candlestick via Lightweight Charts)
- Click ticker → opens Finviz quote (placeholder until `/ticker/{symbol}` ships)

### Pending breadcrumb
- When user clicks "View Queue →" from Copy Insiders, `/pending?ref=copy-trading`
  shows a `← Copy Insiders › Approval Queue` breadcrumb in the left panel.
  Originally placed above `.split-layout` but the negative `margin: -28px -32px`
  was covering it; now placed inside `.split-left`.

### New Universe submenu: Stock Lists
- 10 default ticker collections — S&P 500, NASDAQ-100, Dow 30, S&P 400/600,
  Magnificent 7, FAANG, SPDR Sector ETFs, AI Leaders, Crypto-Adjacent
- Two source types: `wikipedia` (refreshable via `pd.read_html`) and `static`
- Per-list refresh button + global "Refresh dynamic lists"
- Detail page: ticker grid with filter, copy-all, click-through to Finviz
- **Important fix**: `stock_lists.router` registered BEFORE `universe.router`
  in `app.py` so `/universe/stock-lists` doesn't get shadowed by
  `/universe/{preset_name}`.

### Files added/changed
```
A  services/senate_efd_service.py       (eFD scraper + HTML PTR parser + perf adapter)
A  services/stock_lists_service.py      (10 default lists, Wikipedia + static sources)
A  routers/stock_lists.py               (page + JSON API + refresh endpoints)
A  templates/copy_insiders/rankings.html  (leaderboard + multi-follow + composite rank)
A  templates/copy_insiders/trades.html    (multi-select + disclosure table + ticker hover-chart)
A  templates/stock_lists.html           (cards grid)
A  templates/stock_list_detail.html     (ticker grid + filter + copy)
M  app.py                               (register stock_lists router; ordering fix)
M  routers/copy_trading.py              (rewrite around new service + Senate dispatch + many endpoints)
M  routers/pending.py                   (read ?ref=copy-trading param + pass to template)
M  services/capitol_trades_service.py   (rewrote to use ivanma9 API + local yfinance perf)
M  services/db_service.py               (new tables: followed_politicians, member_performance_cache,
                                         stock_lists, senate_filings, senate_trades; CRUD; migrations)
M  services/scheduler.py                (poll job iterates followed_politicians; Senate path)
M  static/app.css                       (.nav-group accordion styles)
M  templates/base.html                  (sidebar rewritten as accordion with parent/child)
M  templates/copy_trading.html          (legacy file kept; route redirects to /copy-insiders/rankings)
M  templates/pending.html               (breadcrumb in .split-left when ref=copy-trading)
M  CLAUDE.md / HANDOFF.md               (this update)
```

### Verified end-to-end against live APIs
- ivanma9 House API: 92 members, Pelosi 61.1% win / +1.23% / +0.86% alpha (n=18)
- eFD Senate scraper: 37 PTRs / 14 senators in last 90 days
- Senate PTR parser: Boozman 64 equity trades across 6 PTRs, **64.1% win
  rate, +2.35% alpha vs SPY**
- All 89 routes register cleanly; DB migrates 12 tables idempotently

### Scheduled jobs: 5 (unchanged this session — auto-diff job is #6, deferred)
- `ct_morning` 07:00 ET Mon-Fri (Capitol Trades poll)
- `ct_poll` 08:30 ET Mon-Fri (Capitol Trades poll)
- `wf_morning_run` 08:30 ET Mon-Fri
- `wf_double_lock_1030` 10:30 ET Mon-Fri
- `wf_evening_run` 16:30 ET Mon-Fri

---

## Immediate next tasks for new session (pick one)

### Option A0 — Multi-source news feed ✅ SHIPPED 2026-04-25 (evening)
Pluggable source registry under `services/news_sources/` with
`AlpacaNewsSource`, `EdgarNewsSource`, and a brand-new `WebullNewsSource`
that hits `https://api.webull.com/quotes/ticker/news` with the
2026 App-Key/Secret access-token in the request header. Adding a new
provider is now a one-file change — drop a `NewsSource` subclass into
the package and append it to `NEWS_SOURCES` in `__init__.py`. The
`MarketHeadlinesWidget` settings schema is now a property that pulls
multiselect choices from the live registry, so the new source surfaces
as a chip in the ⚙ settings panel automatically. Companion changes:
* `services.news_service.get_news_multi_source(symbol, source_ids=, lookback_hours=)`
  fans out to enabled sources in parallel, dedupes by
  `(source, article_id)`, returns newest-first.
* `NewsItem` gained optional `summary` / `image_url` / `tags` /
  `tickers_mentioned` / `extra` fields so per-source uniqueness
  (Webull "hot" indicator, EDGAR `form_type`) survives into the UI.
* New `/news/{source}/{article_id}?symbol=` detail route with a
  full template — title, source badge, sentiment breakdown, VADER
  scores, source-specific extras, "Open original ↗" button. Headlines
  on `/trades/{id}` and the dashboard widget link to this instead of
  popping the source URL directly.
* Headlines widget got a credentials-warning banner: when a source is
  enabled but its env vars are missing, the user sees "⚠ X enabled but
  credentials not set" so silent zero-yield doesn't look like a bug.
* `routers/trade_detail.py` reads the user's saved `enabled_sources`
  from widget_settings so the trade detail news card and the dashboard
  widget honor the same on/off state.

### Option A — Senate auto-diff job ✅ SHIPPED 2026-04-25
`services.scheduler._senate_diff_job` runs 06:00 ET Mon-Sat. Fetches
last-30-days PTRs, diffs against `senate_filings` cache, persists new
ones via `upsert_senate_filings`, bumps `senate_new_filings_count` in
`copy_trading_config`. The rankings page now has a green "N new
disclosures" banner that resets when the user clicks ↻ Senate.
**Note:** the job ID is `senate_daily_diff` (visible in `sched.get_jobs()`).
The all-members API response now includes `senate_new_filings_count`,
`senate_last_diff_at`, and the legacy `senate_last_refresh_at` /
`senate_needs_refresh` (unchanged).

### Option B — News feed polish ✅ SHIPPED 2026-04-25
Three improvements:
1. **News vs filings split** — `_news_card.html` partitions items by
   `source` and renders them under separate "News" and "SEC Filings"
   section headers, each with its own count.
2. **Form-type badges** — `routers/trade_detail.py` extracts a
   structured `form_type` field from the EDGAR headline prefix and
   strips the prefix from `display_headline`. The partial renders a
   colored badge per form type — `filing-8k` (amber), `filing-10q`
   (cyan), `filing-10k` (purple), `filing-s1`/`filing-s3` (lime),
   `filing-def14a`/`filing-defa14a` (pink), gray fallback for the rest.
3. **CIK map prewarm at startup** — new `news_service.prewarm_cik_map()`
   runs as a fire-and-forget background task in app lifespan. The first
   `/trades/{id}` view after a fresh checkout no longer pays the ~3s
   SEC ticker→CIK download cost (10,341 mappings cached on first hit).

### Option C — Phase 5 multi-year backtest engine
Walk-forward replay across cached bars; reuses every Phase 4 agent because
detectors are pure functions of `(bars, config, as_of_ts)`.

### Option D — Persistent APScheduler job store
`close_at_time` jobs live in memory only; an app restart between
scheduling and 15:00 ET drops the close. Add a SQLAlchemyJobStore (or
rehydrate from open positions on startup) to make autonomous intraday
trading restart-safe.

---

## Earlier in 2026-04-25 session (morning) — preserved below

**Phase 4 fully complete.** Scheduler shipped via main `70ccbe6` (Capitol
Trades commit) — workflow YAMLs auto-register from their `schedule:` field.

**Four features shipped this session (2026-04-25):**
1. **Modular dashboard with widget settings layer** — Portfolio/Market/News
   tabs, 5 widgets (sector heatmap, Fear&Greed, SPY trend, strategy health,
   exploded stocks), schema-driven ⚙ settings persisted to SQLite per user.
2. **Unified trade detail page** at `/trades/{id}` — works for active
   pending plans AND closed JSONL trades. Indicator picker (SMA / EMA /
   VWAP / RSI / ATR) persisted per user. Probability of success card
   (backtest WR + live WR sample-size-weighted blend). VADER news
   sentiment card. Postmortem card on closed trades. Levels card.
4. **Phase 6 edit-mode for active trades.** Trade detail page now has
   an Edit button that toggles a form for entry / stop / TP1 / TP2 /
   time-stop deadline. POST `/api/trades/{id}/edit`:
   - Validates input, persists to `plan_json` via
     `db_service.update_plan_json`.
   - If a `broker_order_id` exists and the entry price changed and
     stage is `pending` or `approved`, pushes the change via
     `adapter.modify_order(broker_order_id, {"limit_price": ...})`.
     Phase 4 only places the entry at the broker, so stop/TP/deadline
     are TradePlan-only.
   - If the deadline moved, re-calls `executioner.close_at_time()`
     (idempotent — `close_{plan_id}` job replaces).
   - Refuses non-active stages (closed / rejected / expired) with 409.
   New CSS group `.trade-edit-*` in `static/app.css`. Smoke test:
   `scripts/smoke_trade_edit.py` (6/6 pass).

3. **DL agent loop closed — `executioner.close_at_time()`.** Successful
   entry placement now auto-schedules an APScheduler one-shot date job
   that flattens the position via market order at the plan's
   `time_stop.deadline`. Companion change: `portfolio_manager` computes
   intraday deadlines as today's 15:00 ET (config-overridable) instead
   of `now + 0 days`, and propagates `holding_period` through the plan
   thesis. Smoke test: `scripts/smoke_close_at_time.py` covers happy
   path, research-mode refusal, past/malformed deadline, missing symbol,
   idempotent re-scheduling, and the portfolio_manager intraday
   deadline calculation.

**DL integration: COMPLETE.** `executioner.close_at_time()` shipped this
session — DL plans now auto-schedule a 15:00 ET market-close on successful
entry. Smoke test: `scripts/smoke_close_at_time.py` (7/7 pass).

**Phase 6 edit-mode: COMPLETE.** Active trades (pending / approved / open)
can be edited via the trade detail page. Editable fields: entry, stop,
TP1, TP2, time-stop deadline. Persists to SQLite plan_json; pushes entry
edits to broker via `modify_order` when an order is working; reschedules
the close-at-time job idempotently when the deadline moves. Refuses
edits on closed/rejected/expired trades. Smoke test:
`scripts/smoke_trade_edit.py` (6/6 pass).

**Phase 4.5 chart viewer + indicators: COMPLETE** (was already shipped in
main `730f3f3`; HANDOFF was stale on this point). `routers/indicators.py`
exposes `GET /api/indicators/{symbol}` over the canonical
`services/indicator_service.py`; `static/chart_tools.js` is the shared
panel helper used by `/pending`, `/universe/*/edit`, AND now
`/trades/{id}` (migrated this session — drops ~190 lines of bespoke
chart JS, gains the timeframe selector + chip UX, persists picks via
localStorage `chart.indicators.trade_detail`). Removed in the same
migration: `templates/_partials/_indicator_picker.html`,
`POST /api/trades/chart/indicators`, `_TRADE_CHART_WIDGET_ID` SQLite
storage path. Side fix: `_probability_card.html` now guards on
`probability is none`.

**News feed on `/trades/{id}`: FIXED.** `routers/trade_detail.py` was
calling `news_service.get_news(symbol, start=, end=)` but the service
signature is `(symbol, as_of_ts=None, lookback_hours=N)` — every fetch
was raising and the page rendered an empty news card. Now uses the
correct kwargs (72h lookback), additionally fetches EDGAR filings (30d,
8-K / 10-Q / 10-K), normalizes filings into the NewsItem shape, sorts
newest-first, caps at 30 items, and improves the empty-state copy.
Tested with AAPL (real EDGAR fillings render), SPY (no filings → clean
empty state), and a bogus symbol (graceful empty).

**Dashboard polish: shipped this session.**
- Fear & Greed gauge rebuilt with **proportional band widths** (45° /
  36° / 18° / 36° / 45° matching the 0–25 / 25–45 / 45–55 / 55–75 /
  75–100 score thresholds) instead of uniform 36° wedges, so the band
  color the needle points at always matches the readout. Score + label
  moved inside the SVG hub for a more compact card.
- New `MarketHeadlinesWidget` populates the previously empty News tab.
  Pulls Alpaca news (24h) + EDGAR filings (14d) for a configurable
  watchlist, VADER-scored, sorted newest-first, capped at 25.
- **Universal ⚙ on every widget** (not just configurable ones); the
  panel always offers size cycle + reset, with the schema-driven form
  appearing only for configurable widgets.
- **Drag-to-reorder** widgets within a tab via native HTML5 DnD
  (no library). Order persists per-tab to a synthetic `__layout__`
  widget id under SQLite `user_widget_settings`.
- **Size cycle button** (▣) on every widget header — cycles
  `sm → md → lg → wide`, snaps to the existing 12-col responsive grid.
  Per-widget override stored as `<widget_id>.size` in the same layout
  row. New endpoints: `POST /api/dashboard/layout` (order/size),
  `DELETE /api/dashboard/layout` (reset).

**Next chat options (pick one):**
- (a) **Phase 5 backtest engine** — multi-year Alpaca 30-min replay to
  validate the DL strategy's 82.4% WR on a meaningful sample size.
- (b) **Persistent APScheduler job store** — close_at_time jobs live in
  memory only; an app restart drops the close. Add a SQLAlchemyJobStore
  (or rehydrate from open positions on startup) to make autonomous
  intraday trading restart-safe.
- (c) **News feed enhancements** — distinguish news vs filings visually
  (separate sections or tabs); add the filing form-type badge (8-K /
  10-Q / 10-K) inline; cache the SEC ticker→CIK map at app startup so
  the first `/trades/{id}` view doesn't pay a 3s download.

---

## What shipped this session (2026-04-25)

### Modular dashboard — 3 tabs + 5 widgets + settings infrastructure

Replaced the single hardcoded dashboard with a registry-driven widget grid
under three tabs (**Portfolio** / **Market** / **News**).

**Widgets shipped:**
- `SectorHeatmapWidget` — 11 SPDR sector ETFs as colored tiles (Market tab)
- `FearGreedWidget` — CNN's index as a semicircle SVG gauge (Market tab,
  cached 30 min server-side via httpx)
- `SpyTrendWidget` — 1W/1M/3M/1Y/5Y % returns as a horizontal strip
  (Market tab)
- `StrategyHealthWidget` — per-active-strategy live WR vs backtest WR with
  drift indicator (Portfolio tab)
- `ExplodedStocksWidget` — top up/down movers from a 32-symbol universe,
  user-configurable threshold + max-per-side (Market tab; ⚙ enabled)

**Settings architecture (three-layer):**
1. Global registry in code (`services/dashboard_widgets.py`, `indicator_registry.py`)
2. YAML defaults (`strategy_configs/*.yaml`)
3. SQLite per-user overrides (new `user_widget_settings` table)

**Files:**
```
A  services/dashboard_widgets.py            (Widget ABC + 5 widget classes + WIDGETS registry)
A  services/widget_settings.py              (SQLite get/set/reset, JSON-encoded values)
A  services/indicator_registry.py           (IndicatorSpec catalog: sma20/sma50/sma200/ema20/vwap/rsi/atr)
A  templates/dashboard/widgets/sector_heatmap.html
A  templates/dashboard/widgets/fear_greed.html       (semicircle SVG gauge with 5 color bands + needle)
A  templates/dashboard/widgets/spy_trend.html
A  templates/dashboard/widgets/strategy_health.html
A  templates/dashboard/widgets/exploded_stocks.html
A  templates/dashboard/widgets/_error.html           (per-widget failure isolation card)
A  templates/dashboard/_widget_settings.html         (schema-driven settings modal body)
M  templates/dashboard.html                          (tabs + widget grid + ⚙ icon + modal JS)
M  routers/dashboard.py                              (widget dispatcher + settings endpoints)
M  services/db_service.py                            (user_widget_settings table)
```

**Architecture pattern for adding widgets:**
1. Subclass `Widget`, fill in `id` / `title` / `size` / `tab` / `refresh_seconds`,
   implement `async def get_data()` returning template context.
2. Drop a partial at `templates/dashboard/widgets/{id}.html`.
3. Append the new instance to `WIDGETS` list.

To make a widget user-configurable: set `user_configurable = True` and
populate `settings_schema = {key: {type, default, label, ...}}`. The ⚙
icon, modal, validation, and SQLite persistence work automatically.

### Unified trade detail page (`/trades/{id}`)

Single detail surface for any trade — active or closed — backed by a
storage-agnostic lookup over `pending_approvals` (SQLite) + JSONL trade
journal.

**Cards on the page:**
- Top bar — symbol, direction badge, strategy name, lifecycle stage
- Left col — chart with **indicator chip toggles** (overlay + subplot panes)
- Right col — Levels · Probability of success · News + sentiment
- Postmortem card (closed trades only — auto-gates on `trade.is_closed`)

**Indicator picker:** chip toggles for SMA20 / SMA50 / SMA200 / EMA20 / VWAP
(overlay) + RSI / ATR (subplot). Selection persists per-user via
`user_widget_settings` with `widget_id="trade_chart"` so the same set
loads on any browser/machine.

**Probability blend formula:** sample-size weighted average of
`strategy_configs/{name}.yaml.backtest_summary.point_wr_pct` and live WR
from JSONL trades for that strategy. Confidence rating: strong / moderate /
weak / unknown based on combined n + agreement.

**News sentiment:** VADER (free, lexicon-driven) over Alpaca News results
from `news_service.get_news(symbol, last 24h)`. Returns compound score
[-1, 1] + categorical label (very_negative → very_positive).

**Files:**
```
A  routers/trade_detail.py                  (GET /trades/{id} + POST /api/trades/chart/indicators)
A  services/probability_service.py          (compute() returns ProbabilityEstimate)
A  services/sentiment_service.py            (VADER score_text/score_items/summarize)
A  services/trade_lookup.py                 (unified TradeView over pending_approvals + JSONL)
A  templates/trades/detail.html             (the page; Lightweight Charts + indicator picker JS)
A  templates/_partials/_probability_card.html
A  templates/_partials/_news_card.html
A  templates/_partials/_postmortem_card.html
A  templates/_partials/_indicator_picker.html
M  app.py                                    (registered trade_detail router)
M  templates/trades/_table.html              (clickable rows linking to /trades/{trade_id})
M  templates/trades/analysis.html            (clickable ledger rows when trade_id present)
M  services/analysis_service.py              (per_trade adds trade_id field)
M  static/app.css                            (.trade-detail-*, .prob-*, .news-*, .postmortem-*, .ind-chip, .trade-row-clickable)
```

### Quick-fix: dashboard sizing + production filter on /trades/analysis

- Stat-card font 22→18px and label 11→10px (per user feedback "numbers too huge")
- Fear/Greed gauge max-width 320→200, score 36→24px
- SPY trend rows tightened (padding, gap, font sizes)
- `/trades/analysis` defaults to "production-filter" view (matches the
  82.4% backtest headline). `?raw=1` toggle shows all 81 unfiltered DL signals.
- Empty-frame guards added to every cut function so missing data never
  500s the analysis page.

### Phase 6 (edit-mode) — DEFERRED

Decision: ship Phases 1–5 in this session, defer Phase 6 to next session.
Reason: edit-mode requires testing broker round-trip (`modify_order`)
which is meatier than expected. Want fresh context for that.

Skeleton already in place: every TradeView has an `is_active` property,
the detail page top bar has a placeholder Edit button, and all three
broker adapters (Alpaca, TradeStation, historical) implement
`modify_order(broker_order_id, changes)`. Wiring the form + handler
is the missing piece.

---

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
M  cmds.py                              (rotates between scripts; currently smoke test)
A  scripts/pine/strategy1_FHC.pine
A  scripts/pine/strategy2_DL.pine
```

---

## DL-S2 Python validation + production detector (continued in same session)

After the Pine Script work, we abandoned the TradingView automation route
(focus-steal issues with Windows-MCP, free-tier 60-day intraday limit) and
moved to a Python backtest. Result: **DL-S2 with regime filter hits 82.4% WR**.

### What we did

1. **Backtested DL-S2 with the original Pine parameters** on a 9-symbol mega-cap
   universe → 60% WR (cherry-picked names).
2. **Re-ran on a broad 37-symbol universe** → 43.2% WR. Lossy by itself.
3. **Built indicator correlation analysis** — strongest signals: `rsi14_d` (-0.20),
   `vix_level` (+0.22), `adx14_d` (-0.16). Pattern is regime-sensitive, not pure
   continuation.
4. **Discovered the directional-RSI structure** — LONG wins in mild RSI (40–65),
   SHORT wins in oversold-but-not-collapsing zone (20–40).
5. **Joint filter grid** — found the recipe:
   `LONG RSI[40,65] + SHORT RSI[20,40] + VIX>=20 + ADX<=35` →
   **n=17, WR=82.4%, PF=3.14, +9.5% sum** on 60-day window.
6. **Cross-validated** — time-split 60/40 holds; both halves independently 80–83%;
   leave-one-symbol-out aggregates 82.4%; bootstrap 95% CI [64.7%, 100%].
7. **Tested 7 trailing-stop variants** — all but one HURT the strategy. Winner:
   `pct_post_1r_loose` (1.0% trail activated only after +1.0R favorable). Same
   82.4% WR as baseline, only triggers on outsized winners (~1 of 17 trades).
8. **Built the production detector + config + workflow + smoke test.**

### Files added (continuation)

```
A  scripts/backtest_strategy2_dl.py             (parameter sweep, 9-sym → 37-sym)
A  scripts/backtest_strategy2_indicators.py     (10-indicator correlation, dump CSV)
A  scripts/backtest_strategy2_round2.py         (direction × indicator interactions)
A  scripts/backtest_strategy2_round3.py         (RSI range scan + VIX/ADX layers)
A  scripts/cross_validate_dl.py                 (time-split + bootstrap CI)
A  scripts/test_trailing_stops.py               (7 exit-policy variants)
A  scripts/smoke_double_lock_filtered.py        (production detector reproduces dump)
A  agents/detectors/double_lock_filtered.py     (the production detector)
A  strategy_configs/double_lock.yaml            (thresholds, trail, R:R override)
A  workflows/double_lock_1030.yaml              (10:30 ET workflow spec)
M  agents/detectors/__init__.py                 (added INTRADAY_DETECTORS registry)
A  claude_trades_dump.csv                       (81 trades + 10 features per trade)
```

### Failure-analysis dashboard — `/trades/analysis`

Replaces the Phase 6 placeholder with a real analysis surface. Built BEFORE
agent integration so it's useful today against the backtest dump and stays
useful once trades start writing JSONL (data source auto-switches).

```
A  services/analysis_service.py                 (data layer; reads dump CSV or JSONL)
A  routers/analysis.py                          (page + JSON endpoints)
M  templates/trades/analysis.html               (replaced placeholder with full UI)
M  routers/trades.py                            (removed /trades/analysis stub route)
M  app.py                                       (registered analysis router)
```

The page surfaces:
1. **Headline summary card** with live WR vs backtest claim + drift badge
   (`above-backtest` / `within-ci` / `below-ci`). Verified: production-filtered
   dump returns 82.4% WR / drift 0.0 / "within-ci" exactly matching the
   backtest headline.
2. **By direction** — LONG vs SHORT WR/PF
3. **By indicator quartile** — RSI(14), VIX, ADX(14) bucketed
4. **By binary indicator** — spy_aligned, above_sma50_d, prior_day_match
5. **Loser clusters** — failure modes grouped by RSI/VIX quartile + exit reason
6. **Per-symbol breakdown** — WR/PF/total per ticker
7. **Equity curve** chart (Lightweight Charts; aggregates same-day pnl)
8. **Per-trade ledger** with full feature vector at entry (most recent 200)

**Production-filter toggle** at top-right: default view applies the
`strategy_configs/double_lock.yaml` thresholds (VIX≥20, ADX≤35, RSI ranges)
so the pre-launch view shows what live trade analytics will look like.
`?raw=1` shows every raw DL candle hit for the "should we relax the filter?"
debate.

**Auto data-source switch:** `services.analysis_service.load_trades(source="auto")`
returns JSONL data once `trade_logs/*.jsonl` files exist; falls back to the
dump CSV otherwise. No change needed when the agent ships.

### Smoke test result

`87% reproduction rate (14/15 reachable fires), 0 false positives.` The 2 missing
fires on 2026-03-02 are explained by yfinance's rolling-window drift (RSI/ADX/slot
volume baselines shift between the dump generation and the smoke run). PQS scores
on matched fires: 83–100. Detector logic is sound.

### Integration TODO progress — 3 of 5 landed this session

The detector lives in `INTRADAY_DETECTORS = {"double_lock_filtered": ...}` and
takes `(bars_30m, daily, vix_prev_close, config, as_of_ts)`. Five integration
changes were planned. **Three landed; two remain.**

#### ✅ TODO #1 — `services/data_service.py` 30m support
- `Interval = Literal["1d", "1h", "30m"]`
- `_DEFAULT_PERIOD["30m"] = "60d"` (yfinance cap)
- 30m bars cache the same way as 1h/1d in `data/historical/{SYM}_30m.csv`
- Verified: smoke pulls 780 rows × 16 symbols cleanly

#### ✅ TODO #2 — `agents/analyst.py` intraday lens (option 2b)
New methods:
- `run_lens_intraday(symbol, bars_30m, daily, vix_prev_close, config, as_of_ts)`
  iterates `INTRADAY_DETECTORS` with the right signature
- `Analyst.run_intraday(symbol, macro_context, as_of_ts)` orchestrates
  30m + daily + VIX fetch and emits `Signal(timeframe="intraday")` objects
- `run_intraday_on_shortlist(...)` — parallel runner mirroring the swing one,
  defaults `strategy_name="double_lock"`

The swing path is untouched; intraday is a separate code path so the workflow
engine can dispatch to one or the other based on `lenses` field in the YAML.

#### ✅ TODO #3 — `agents/portfolio_manager.py` config-driven trail mode
`_build_plan` now reads `trail_mode` from strategy config (default `"atr"` for
back-compat). Supports `atr` / `percent` / `structural`. The `double_lock.yaml`
specifies `trail_mode: percent` + `trail_percent: 1.0` and that propagates
through to the final TradePlan. Verified end-to-end in
`scripts/smoke_intraday_pipeline.py`.

#### ✅ TODO #4 — `agents/executioner.py` `close_at_time(plan, deadline, qty)`
Shipped 2026-04-25. New method registers a one-shot APScheduler `date`
job at `time_stop.deadline` keyed by `close_{plan_id}` (replaces on
re-call). `_close_position_job` resolves the adapter at fire time,
flattens via market order with the inverse side (`long` → `sell`,
`short` → `buy_to_cover`). `execute_plan` auto-calls it on successful
entry placement when `plan.setup.stop_loss.time_stop.active`. Refuses
research mode, missing symbol, past/malformed deadline, qty<=0.
Companion change: `agents/portfolio_manager.py` now reads
`strategy_config.holding_period` and computes today's 15:00 ET (next
day if past) for intraday plans, falling back to `now + sessions days`
for swing. The thesis `expected_holding_period` is now config-driven
instead of hardcoded `swing_days`. **Reliability caveat:** APScheduler
uses an in-memory job store, so an app restart between scheduling and
the deadline drops the close. Persistent job store (e.g. SQLAlchemy)
or startup re-hydration from open positions is a follow-up.

#### ✅ TODO #5 — `services/scheduler.py` — DONE by main `70ccbe6`
APScheduler service shipped as part of the Capitol Trades copy-trading work.
It auto-globs `workflows/*.yaml`, reads the `schedule:` field, and registers
a cron job per workflow. **`workflows/double_lock_1030.yaml` with
`schedule: "30 10 * * 1-5"` is picked up automatically at app startup** — no
extra registration code needed (see `_register_workflow_jobs` in
`services/scheduler.py`).

Estimated remaining work: **~1 hour focused** for #4 only.

### Smoke test that proves the wired path works

`scripts/smoke_intraday_pipeline.py` exercises the full pipeline end-to-end:

```
data_service.get_bars("30m")       (16 symbols, 780 rows each)
    -> compute_macro_context        (SPY trend, VIX level)
    -> run_intraday_on_shortlist    (parallel, async)
       -> Analyst.run_intraday      (per symbol)
          -> run_lens_intraday      (calls INTRADAY_DETECTORS)
             -> double_lock_filtered (the actual detector)
    -> PortfolioManager.process_signals
    -> TradePlan with trail.mode='percent'
```

Run via `cmds.py`. Today's regime (VIX 18.71 < 20 threshold) means no live
signals fire, so the smoke falls back to a hand-built synthetic signal to
confirm the trail block populates correctly. Either path lands in `[4] PASS`.

### Files added/changed this session (continuation, post-detector)

```
M  services/data_service.py             (30m interval support)
M  agents/analyst.py                    (run_lens_intraday + Analyst.run_intraday + parallel runner)
M  agents/portfolio_manager.py          (config-driven trail_mode)
A  scripts/smoke_intraday_pipeline.py   (end-to-end pipeline smoke test)
M  cmds.py                              (rotated to point at the new smoke)
A  data/historical/{SYM}_30m.csv        (16 newly cached 30m frames)
```

### Backtest caveat (read before claiming production-ready)

- **n=17 is small.** Bootstrap 95% CI is [64.7%, 100%] — wide.
- **60-day window is short** (yfinance free-tier cap on 15-min data).
- **Multiple-comparisons inflation:** I tried hundreds of filter combos to
  find the 82.4% recipe. Even with cross-validation surviving, expect 5-10
  pp drag on truly out-of-sample data going forward.
- **Realistic claim**: "expected WR 65-85%, point estimate 82%."
- **De-risking path**: extend to multi-year via Alpaca's 30-min API
  (credentials already in `.env`) once Phase 5 backtest engine lands.

---

## Immediate next tasks for new session

Pick one. Each is self-contained.

### Option A — Finish DL-Filtered integration (3-4 hr)
Implement the 5 integration TODOs above. End state: scheduler fires
`workflows/double_lock_1030.yaml` daily at 10:30 ET, paper trades flow
through the existing approval queue, and we collect real OOS data.

### Option B — Phase 4.5 chart viewer + indicators push (per existing plan below)
Continue with the chart-viewer multi-source + indicators work that was on
the roadmap before the DL detour.

### Option C — Phase 5 backtest engine
Reuse the DL-Filtered detector as the first Phase 5 demo — walk-forward
across multiple years (Alpaca 30-min) to nail down the true OOS WR.

### Option D — Strategy 3 (Failed Follow-Through Reversal)
Original plan. If user wants more pattern variety before deepening Strategy 2.

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
