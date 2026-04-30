# Sidebar Restructure & Information Architecture

**Status:** design proposal (Plan B step 2) · 2026-04-29
**Depends on:** [glossary_and_audit.md](glossary_and_audit.md) (vocabulary)
**Awaiting:** confirmation of Q4 understanding + 4 follow-ups in §5

This is a design document. **No code changes happen until you sign off.**

---

## 1. Proposed sidebar tree (revised from your sketch)

Your original sketch had **Base Universe** and **Favorites** as siblings
under Filtered Symbol Sets. Q2's answer changes that — "the universe" is
now a *flag on one Stock List*, not a separate page. So Base Universe
collapses into Stock Lists, and the tree becomes:

```
Dashboard
Pending Approvals  [N]
─────────────────────────────────────
Trade Setups
├── Filtered Symbol Sets
│   ├── Stock Lists       ← lists by category; one is the active universe (pinned)
│   ├── Screeners         ← filter recipes (Finviz-driven; produce stock lists)
│   └── Favorites         ← per-symbol watchlist with source tooltip
└── Strategies
    ├── Validated         ← cleared the backtest bar (DL today)
    ├── In Progress       ← under research (breakout_empirical, vcp_absorption)
    └── Archived          ← retired; manual move only
─────────────────────────────────────
Trade History
Analysis
Copy Insiders
├── Politician Rankings
└── Politician Trades
─────────────────────────────────────
Broker
Settings
Console
```

### What changed vs your sketch
- `Base Universe` removed as a sibling; lives inside Stock Lists as
  the "active universe" pin (per Q2).
- `Screeners` added as a child of Filtered Symbol Sets, not under
  Stock Lists. Reason in §3 — open question to confirm.
- `Trade Setups` becomes a *visual section header* (group label with a
  divider above it), not a clickable parent. The two children
  **Filtered Symbol Sets** and **Strategies** are real parent rows
  with chevrons.
- Existing top-level entries (`Dashboard`, `Pending Approvals`,
  `Trade History`, `Analysis`, `Copy Insiders`, `Broker`, `Settings`,
  `Console`) keep their current positions.

### What disappears
- The current top-level `Universe` group → renamed to
  `Filtered Symbol Sets` and gains a Favorites child.
- The current top-level `Strategies` row (sidebar leaf at line 34 of
  `templates/base.html`) → demoted to a parent with three children.

---

## 2. Page-level layout sketches

### 2.1 Filtered Symbol Sets / Stock Lists

```
┌─ Stock Lists ────────────────────────────────────────────┐
│  + New List   + New Category    [search ___________]  ⚙ │
│                                                          │
│  ★ ACTIVE UNIVERSE                                       │
│  ┌───────────────────────────────────────────────────┐   │
│  │ Liquid Momentum Core              ●  117 tickers  │   │
│  │ from screener: liquid_momentum_core               │   │
│  │ refreshed 2h ago · auto-refresh on (daily 8:00ET) │   │
│  │ [unpin] [refresh now] [view]                      │   │
│  └───────────────────────────────────────────────────┘   │
│                                                          │
│  Indices                                                 │
│   • S&P 500              500    ↻ wikipedia              │
│   • S&P 400              400    ↻ wikipedia              │
│   • NASDAQ-100           100    ↻ wikipedia              │
│   • Dow 30                30    ↻ wikipedia              │
│                                                          │
│  Themes                                                  │
│   • Magnificent 7          7    static                   │
│   • FAANG                  5    static                   │
│   • AI Leaders            12    static                   │
│                                                          │
│  Sectors                                                 │
│   • XLK · Technology     ETF holdings                    │
│   • XLF · Financials     ETF holdings                    │
│   ... (8 more)                                           │
│                                                          │
│  My Lists                                                │
│   • (empty — click + New List)                           │
└──────────────────────────────────────────────────────────┘
```

Behavior:
- Pin button (★) on each list card → makes it the active universe;
  exactly one can be pinned at a time. New pin replaces the old.
- "+ New Category" prompts for a name; categories are user-mutable
  buckets that group lists alphabetically inside the page.
- "+ New List" supports three creation modes: **Manual paste**,
  **From screener** (picks an existing screener and stores its current
  result), **From source** (Wikipedia URL / static array / sector
  ETF holdings).
- Clicking a list card opens the existing
  `templates/stock_lists.html`-style ticker grid.

### 2.2 Filtered Symbol Sets / Screeners

Same as today's `/universe` page, just relabeled. No structural change.
Screeners *produce* Stock Lists when "Save as universe / Save as list"
is clicked. (See open question Q-S in §5.)

### 2.3 Filtered Symbol Sets / Favorites

```
┌─ Favorites ──────────────────────────────────────────────┐
│  [+ Add Symbol]                  [search ___________]    │
│                                                          │
│  Symbol  Last     Δ Day    Source              Added     │
│  ────────────────────────────────────────────────────    │
│  NVDA   $945.20  +1.4%    [from Pelosi disclosure]  2d   │
│  PLTR    $44.10  +3.1%    [hand-typed]              5d   │
│  AAPL   $241.55  -0.6%    [from S&P 500 list]      11d   │
│                                                          │
│  Hover the source pill → tooltip shows the full origin   │
│  ("Politician Trades · Pelosi · 2026-04-22")             │
└──────────────────────────────────────────────────────────┘
```

Adding from anywhere: every place a ticker shows up in the app
(politician disclosure rows, screener results, stock list cards,
trade history) gets a `★` action that adds the symbol to Favorites,
recording where it came from in the `source` field.

Schema sketch:
```sql
CREATE TABLE favorites (
  symbol         TEXT NOT NULL,
  source_type    TEXT NOT NULL,    -- 'politician', 'screener', 'list', 'trade', 'manual'
  source_ref     TEXT,             -- e.g. 'pelosi', 'liquid_momentum_core', 'sp500'
  source_label   TEXT,             -- human-readable: 'Politician Trades · Pelosi · 2026-04-22'
  added_at       TEXT NOT NULL,
  notes          TEXT,
  PRIMARY KEY (symbol)
);
```
One row per symbol; `source_*` records the *first* place it was added
(replacing source on re-add can be optional).

### 2.4 Strategies / Validated, In Progress, Archived

```
┌─ Strategies ─────────────────────────────────────────────┐
│  [+ New Strategy]                                        │
│  ┌─ Validated ───┬─ In Progress ───┬─ Archived ───┐      │
│                                                          │
│  Validated (1)                                           │
│   ┌─────────────────────────────────────────────────┐    │
│   │ Double Lock (DL)                          ★     │    │
│   │ intraday · 10:30 ET entry · 15:00 ET exit       │    │
│   │ ✓ Pine backtest: 82.4% WR (n=17, 60d)           │    │
│   │ ✓ Python backtest: matches Pine ±2bp             │    │
│   │ ◯ Live paper: 0 trades yet                      │    │
│   │                                                 │    │
│   │ [Open] [Pine Editor↗] [Edit] [Archive]          │    │
│   └─────────────────────────────────────────────────┘    │
│                                                          │
│  In Progress (2)                                         │
│   • Empirical Breakout      ◯ Pine ✓  ◯ Py ✓  ◯ Live    │
│   • VCP Absorption          ◯ Pine ◯  ◯ Py ◯  ◯ Live    │
└──────────────────────────────────────────────────────────┘
```

### 2.5 Strategies / Strategy detail page

```
┌─ Strategy: Double Lock ──────────────────────────────────┐
│  Status: Validated · Active in workflow double_lock_1030 │
│                                                          │
│  ├─ Definition ─┬─ Pine ─┬─ Validation ─┬─ Live runs ─┐  │
│                                                          │
│  [Definition tab]                                        │
│   YAML editor (strategy_configs/double_lock.yaml)        │
│   thresholds, risk, exits, schedule, screener            │
│                                                          │
│  [Pine tab]                                              │
│   ┌─────────────────────────────────────────────────┐    │
│   │ //@version=6                                    │    │
│   │ strategy("Double Lock", ...)                    │    │
│   │ ...                                             │    │
│   └─────────────────────────────────────────────────┘    │
│   [Copy] [Download .pine] [Open in TradingView]          │
│   ☐ Auto-regenerate from YAML on save                    │
│                                                          │
│  [Validation tab]                                        │
│   Pine backtest:    82.4% WR · n=17 · 60d  (≥ threshold) │
│   Python backtest:  82.0% WR · n=17 · 60d                │
│   Live paper:       0 trades                             │
│   → Validation status: ✓ Validated (auto-promoted)       │
│                                                          │
│  [Live runs tab]                                         │
│   strategy_runs table for this strategy, 30 most recent  │
│   IDLE → SCOUTING → ARMED → DEFERRED (or → FILLED)       │
└──────────────────────────────────────────────────────────┘
```

---

## 3. Q4 — restating my understanding for confirmation

You said: "ultimately, a strategy has to be generated as pine and
tested. The Pine should be stored, downloadable, copyable, and
editable. If it can be directly opened in trading view, lets add
this."

What I'm reading:

1. **YAML is the source of truth** for a strategy's *definition*
   (thresholds, risk, screener, schedule). One file in
   `strategy_configs/`, like `double_lock.yaml` today.
2. **Pine is generated from the YAML.** Each strategy template
   knows how to render itself as Pine v6 code. The Python detector
   in `agents/detectors/` is hand-written and paired with the YAML
   by name — it does *not* need to be auto-generated; just kept in
   sync.
3. **Pine artifact is a first-class object in the UI:** copy to
   clipboard, download `.pine`, view-as-code (Monaco/Prism). When
   YAML thresholds change, Pine regenerates on save.
4. **"Open in TradingView"** — TradingView doesn't have a public
   URL that prefills code. Best we can do:
   click → copies code to clipboard + opens
   `https://www.tradingview.com/chart/?symbol=SPY` in a new tab →
   user pastes into Pine Editor (Ctrl+V). Two-step UX, not seamless,
   but matches every other tool that integrates with Pine.
5. **Editing Pine directly:** v1 = view-only (regenerated from YAML).
   v2 (later) = a "fork" mode that decouples Pine from YAML so the
   user can hand-tune Pine without losing it on the next regen.

**Validation evidence comes from three sources, stacked:**
- (a) Pine backtest results pasted in / scraped from TradingView
- (b) Python backtest run by the in-app engine (Phase 5)
- (c) Live paper-trading WR over a configurable window
A strategy auto-promotes to **Validated** when *any* source clears
its threshold; **Archived** is always manual; **In Progress** is the
default for newly created strategies.

**Confirm or correct any of these five points** before I draft the
state-machine model in step 3.

---

## 4. Cleanup plan (per Q5)

### Hard delete
9 swing detectors that have never been validated, never had a
backtest summary, never produced a live trade:

```
agents/detectors/ascending_triangle.py
agents/detectors/bull_flag.py
agents/detectors/cup_and_handle.py
agents/detectors/double_bottom_top.py
agents/detectors/inside_bar_nr7.py
agents/detectors/rsi_divergence.py
agents/detectors/volatility_squeeze.py
agents/detectors/vwap_reclaim.py
agents/detectors/wyckoff_accumulation.py
```

Plus their config / workflows:
```
strategy_configs/swing_momentum.yaml          (references all 9)
workflows/morning_run.yaml                    (runs swing_momentum)
workflows/evening_run.yaml                    (runs swing_momentum)
workflows/research_run.yaml                   (runs swing_momentum)
```

Plus registry refs in:
```
agents/detectors/__init__.py     — drop ALL_DETECTORS swing entries
agents/analyst.py                — drop swing pattern import block
```

### Keep, classified as "In Progress" (per Q3 hybrid)
Two detectors that are research-stage with docs and Pine but no
backtest_summary in a YAML:

```
agents/detectors/breakout_empirical.py
agents/detectors/vcp_absorption.py
docs/indicators/empirical_breakout.md
docs/indicators/vcp_absorption.md
pine/empirical_breakout_v1_indicator.pine
pine/empirical_breakout_v1_strategy.pine
```

**These need YAMLs created in `strategy_configs/`** to become
first-class strategies. That's part of step 3, not cleanup.

### Keep as-is
```
agents/detectors/double_lock_filtered.py
agents/detectors/_helpers.py
strategy_configs/double_lock.yaml
workflows/double_lock_1030.yaml
scripts/pine/strategy1_FHC.pine    (research artefact — keep next to strategy2)
scripts/pine/strategy2_DL.pine     (DL Pine v2)
```

---

## 5. Open questions for you (4 left)

### Q-S — Where do Screeners live?
Two options:
- **(a) Sidebar leaf under Filtered Symbol Sets.** Screeners are a
  first-class tool the user navigates to directly. Saving a screener
  result writes a Stock List as a side effect.
- **(b) Plumbing under Stock Lists.** Screeners only surface as a
  "+ New List → from screener" creation mode. No standalone screener
  page; the recipe lives inline on the resulting stock list's edit
  page.

(a) preserves today's `/universe` page; (b) is a deeper restructure.
I lean (a) for v1 — less migration, you already have a working
screener page.

### Q-J — `routers/jobs.py` — should it exist?
Currently no `/jobs` route exists on any branch. CLAUDE.md describes
job orchestration via `services/scheduler.py` (APScheduler reads
workflow YAML `schedule:` fields). Three options:
- **(a) Skip it.** No /jobs page; jobs are config in YAML, observable
  through the existing alerts banner and Console.
- **(b) Build it as a status-only page.** List of registered cron
  jobs with `last_run`, `next_run`, `last_status`, "Run now" button.
  Read-only — editing means editing YAML.
- **(c) Build it as a full CRUD page.** Create/edit jobs in the UI,
  with the YAML autogenerated.

I lean (b) — there's enough cron going on (DL Lock 1 scout, DL 10:30
fire, hosted-API refreshes, Senate refresh) to want a single place to
see "what's scheduled and when did it last run". (c) is a Phase-7
nice-to-have.

### Q-T — `routers/strategies.py` — what does it own?
The sidebar already links to `/strategies` (currently a stub in
`routers/stubs.py`). Step 3 will replace it. What it owns:
- **GET /strategies** → the three-tab list view (Validated / In
  Progress / Archived).
- **GET /strategies/{slug}** → strategy detail (Definition / Pine /
  Validation / Live runs tabs).
- **POST /strategies** → create new (form: name, slug, base
  template).
- **POST /strategies/{slug}/regenerate-pine** → re-render Pine from
  YAML.
- **POST /strategies/{slug}/archive** / **POST /unarchive** →
  manual state moves.
- **POST /strategies/{slug}/validation/pine** → record a Pine
  backtest result (paste-in form: WR, sample size, timeframe).

Confirm this surface or trim/extend.

### Q-PE — Pine editing in v1
- **(a) View-only.** Pine is rendered from YAML; user copies/downloads
  but can't edit in-app. To change Pine, edit YAML thresholds.
- **(b) View + override.** Pine is rendered, but the user can flip a
  "manual override" toggle to hand-edit the file; YAML regen is
  disabled until they revert.

(a) is half the work and avoids two-sources-of-truth. I lean (a) for
v1, (b) when someone actually asks for it.

---

## 6. What this proposal does *not* yet decide

- Database migration plan for renaming the
  `universe_presets` table → `screeners`.
- The `strategy_runs` state machine (IDLE → SCOUTING → ARMED →
  DEFERRED) and the extended `pending_approvals` lifecycle. Both go
  in step 3.
- The Pine codegen template engine. Step 3.
- How `agents/copy_trader.py` interacts with Favorites (a copy-trade
  is one source-tagged Favorite plus an executioner path).

---

## 7. Sign-off needed before I write any code

1. **Confirm the sidebar tree in §1** (or red-line edits).
2. **Confirm Q4 understanding in §3** (the five Pine-codegen points).
3. **Answer Q-S, Q-J, Q-T, Q-PE in §5.**

Once those land, step 3 (strategy as first-class concept + state
machines) becomes a focused design pass.
