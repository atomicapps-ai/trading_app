# Phase 2 Build Prompt — UI Shell
Paste this entire prompt into VS Code Claude to begin Phase 2.

---

We are building Phase 2 of the TradeAgent application. Read CLAUDE.md before
writing any code. All architectural rules in CLAUDE.md apply.

## Design system (apply to every template)

**Theme:** Dark. Background is #0f1117. Surface cards are #1a1d27.
Sidebar and topbar are #13151f. Borders are rgba(255,255,255,0.07).
Primary text is #e8e9ed. Secondary text is #8b8fa8. Accent green is #1db87a.
Accent amber is #e6a817. Accent red is #e05252. Accent blue is #4a9eff.

**Typography:** System font stack: -apple-system, 'Segoe UI', sans-serif.
Base size 14px. Line height 1.6. Font weights: 400 regular, 500 medium only.
No bold (700). No italics in UI chrome.

**Spacing:** Comfortable. Card padding 20px 24px. Section gaps 24px.
Sidebar width 200px. Topbar height 52px. Min content width 1200px.
Designed for multi-monitor use — content breathes, nothing cramped.

**Components:**
- Cards: background #1a1d27, border 0.5px rgba(255,255,255,0.07),
  border-radius 10px, padding 20px 24px
- Stat cards: background #141720, no border, border-radius 8px
- Badges/pills: font-size 11px, padding 2px 9px, border-radius 4px,
  font-weight 500
- Buttons: border-radius 6px, padding 7px 16px, font-size 13px,
  font-weight 500, border 0.5px
- Nav items: padding 9px 16px, border-radius 6px, font-size 13px
- Active nav: background rgba(74,158,255,0.12), color #4a9eff
- Hover states: background rgba(255,255,255,0.04)
- Inputs: background #0f1117, border 0.5px rgba(255,255,255,0.12),
  border-radius 6px, padding 7px 12px, font-size 13px, color #e8e9ed
- Table rows: border-bottom 0.5px rgba(255,255,255,0.05),
  hover background rgba(255,255,255,0.03)

**HTMX pattern:** All partial updates use hx-get/hx-post with
hx-target and hx-swap="innerHTML". Check HX-Request header in routes
to return partial vs full template. Use hx-trigger="load" for
auto-loading content on page open.

---

## Files to build in Phase 2

Build in this exact order. Complete and verify each file before moving
to the next.

### Step 1 — static/app.css
Global CSS using the design system above. Include:
- CSS custom properties (--bg-base, --bg-surface, --bg-sidebar,
  --border, --text-primary, --text-secondary, --accent-green,
  --accent-amber, --accent-red, --accent-blue, --radius-card,
  --radius-btn) mapped to the hex values above
- Reset: box-sizing border-box, margin 0, padding 0
- Body: background var(--bg-base), color var(--text-primary),
  font-family system stack, font-size 14px
- Utility classes: .badge-green .badge-amber .badge-red .badge-blue
  .badge-gray (colored pill variants), .text-secondary, .text-accent-green,
  .text-accent-red, .mono (monospace for prices)
- Stat card class: .stat-card with label (11px, secondary) and
  value (22px, 500) and sub (11px, tertiary)
- Table base styles: .data-table (full width, border-collapse collapse,
  th 11px uppercase secondary, td 13px, row hover)
- Status dot: .dot.green .dot.amber .dot.red (8px circle, colored)
- Gate pill: .gate-pass .gate-block .gate-warn .gate-resize
  (colored small pills for compliance/risk verdicts)
- Agent status card: .agent-card (flex, gap 10px, surface bg,
  border-radius 8px, padding 10px 14px)
- Responsive: no mobile breakpoints needed (desktop only)

### Step 2 — templates/base.html
Main shell template. Include:
- DOCTYPE, html lang="en", dark meta theme-color
- Head: charset, viewport, title block, app.css link,
  htmx.min.js script (load from /static/htmx.min.js)
- Body layout: CSS grid, 200px sidebar + 1fr main, 52px topbar
- Topbar content:
  - Left: app name "TradeAgent" (14px, 500) + mode badge
    (RESEARCH/PAPER/LIVE with appropriate color)
  - Right: broker connection dot + label, Tailscale dot + label,
    current ET time (updates every minute via JS), separator,
    emergency HALT button (red, small, confirmation dialog before firing)
  - Mode badge colors: RESEARCH=#4a9eff bg, PAPER=#e6a817 bg, LIVE=#1db87a bg
    all with dark text
- Sidebar content:
  - App logo area (top 16px)
  - Nav links with icons (use simple SVG inline icons, not an icon library):
    Dashboard (grid icon), Pending Approvals (clock icon + badge span
    id="pending-badge" auto-populated), Universe (filter icon),
    Trade History (list icon), Analysis (chart icon), Strategies (sliders icon),
    Broker (link icon), Settings (gear icon), Console (terminal icon)
  - Nav icons: 15px, color var(--text-secondary), flex align-items center gap 8px
  - Bottom of sidebar: version string "v1.0.0" and current user from settings
  - Active page highlighting via Jinja2 `active_page` context variable
- Main content area: overflow-y auto, padding 28px 32px
- Jinja2 blocks: title, content, scripts
- JS in base: ET clock update, pending badge poll (hx-get /api/pending/count
  every 30s), HALT button confirmation

### Step 3 — routers/dashboard.py + templates/dashboard.html

**router:**
- GET / → render dashboard.html with account state stub and agent status
- GET /api/dashboard/stats → HTMX partial: stat cards (loads on page open)
- GET /api/dashboard/agents → HTMX partial: agent status grid
- GET /api/pending/count → returns pending count integer for badge

**template layout (dashboard.html):**
Two-column layout: left col 65%, right col 35%, gap 24px.

Left column top: stat row (4 stat cards in a grid):
- Portfolio value (large number, green if positive day)
- Day P&L (colored green/red, with percentage)
- Buying power (with "X% of equity" sub)
- Open positions (X / max sub)

Left column middle: "Pending approvals" section header with count badge.
If pending > 0: show compact approval cards (symbol, direction badge,
strategy tag, entry/stop/TP1 prices, risk USD, conviction %, time created,
[Review] button that navigates to /pending). Limit 3 visible, "View all" link.
If pending = 0: empty state "No trades awaiting approval".

Left column bottom: "Open positions" table.
Columns: Symbol, Direction, Entry, Current, P&L $, P&L %, R-multiple,
Stop, Strategy, [Close] button (disabled stub in v1 — show tooltip
"Manual close: use broker platform").
Empty state if no positions.

Right column top: "Agent status" — vertical stack of agent cards.
Each card: status dot (green/amber/red) + agent name + status line.
Agents: universe_filter, analyst (4 lenses), portfolio_manager,
compliance_officer, risk_manager, executioner.
Status text examples: "312 symbols · last run 08:00 ET",
"4 lenses active · 3 signals today", "awaiting approval", "idle".

Right column bottom: "Today's activity" — compact log of today's
compliance blocks, risk events, fills, and agent decisions.
Simple list: timestamp + icon + description. Max 10 items, newest first.
HTMX auto-refresh every 60s.

All data is stubbed with realistic placeholder values for Phase 2.
Real data wired in Phase 4/5.

### Step 4 — routers/settings.py + templates/settings.html

**router:**
- GET /settings → render settings.html with current settings.yaml content
- POST /settings → validate + write settings.yaml, return success partial

**template layout:**
Single column, max-width 760px, centered. Sections separated by
horizontal rules with section labels.

Section 1 — Application:
- Mode selector: radio buttons styled as a segmented control
  (RESEARCH / PAPER / LIVE). LIVE shows a warning "Real money — all trades
  require approval" below when selected.
- Port (number input, default 5000)
- Tailscale hostname (text input)

Section 2 — Risk defaults:
- Max risk per trade % (number input, step 0.1, max 5.0)
- Max position size % of equity (number input, step 0.5)
- Max daily loss % (number input, step 0.1)
- Max open positions (integer, max 20)
- Max daily trades (integer, max 50)
- Min R:R ratio (number input, step 0.1)
- Participation cap % ADV (number input, step 0.5)
- Max spread bps (integer)
- Max sector concentration % (number input, step 1.0)

Section 3 — Compliance:
- Earnings blackout hours (integer, toggle to enable/disable)
- Wash sale tracking (toggle)
- Restricted symbols (textarea, one symbol per line)

Section 4 — Notifications (ntfy):
- ntfy server URL (text input)
- ntfy topic (text input)
- Test notification button (POST /api/ntfy/test, shows
  "Notification sent" inline via HTMX)

Section 5 — Data paths (read-only display, not editable via UI):
Show resolved paths for trade_logs, universe_filters, strategy_configs,
settings file, local db. Label: "Configure in settings.yaml directly".

Footer: [Save settings] button (POST /settings, HTMX swap success message).
Show last-saved timestamp.

### Step 5 — routers/trades.py + templates/trades.html

**router:**
- GET /trades → render trades.html
- GET /api/trades → HTMX partial: trade table, supports query params:
  ?symbol=&strategy=&outcome=win|loss|all&date_from=&date_to=&limit=50
- Read from JSONL files in TRADE_LOG_DIR, aggregate across months

**template layout:**
Full width. Filter bar at top, table below.

Filter bar (horizontal, single row):
- Symbol search (text input, short)
- Strategy dropdown (populated from unique strategy_name values in logs)
- Outcome filter: All / Wins / Losses (segmented control)
- Date range: from / to (date inputs)
- [Filter] button (hx-get /api/trades with params)
- [Export CSV] button (stub, show "Coming soon" tooltip)

Trade table columns:
Date | Symbol | Direction | Strategy | Entry | Exit | P&L $ | P&L R | MFE R | MAE R |
Hold time | Exit reason | Mode | Detail

- Date: formatted "Jan 15 10:33"
- Direction: colored badge (LONG green, SHORT red)
- P&L $: colored (green positive, red negative), 2 decimal places
- P&L R: colored, show as "+1.53R" or "-0.82R"
- MFE R / MAE R: secondary color, smaller
- Hold time: human readable "4h 22m" or "2d 3h"
- Exit reason: badge (tp1_hit, trailing_stop, time_stop, thesis_invalidation, manual)
- Mode: tiny badge (paper/live/research)
- Detail: [→] icon link to /trades/{trade_id}

Empty state: "No trades recorded yet. Complete the agent setup to begin
paper trading."

Stub the log_service.py read in Phase 2: return 3 hardcoded TradeRecord
dicts so the table renders with real structure. Replace with real JSONL
reads in Phase 5.

---

## Stub data to use across Phase 2 templates

Use this consistent stub data so all screens feel coherent:

```python
STUB_ACCOUNT = {
    "equity": 162480.00,
    "buying_power": 48220.00,
    "day_pnl_usd": 847.50,
    "day_pnl_pct": 0.52,
    "unrealized_pnl": 2340.00,
    "open_positions": 3,
    "max_positions": 8,
    "trades_today": 2,
    "mode": "paper",
    "broker": "tradestation_sim",
    "connected": True
}

STUB_AGENTS = [
    {"name": "universe_filter", "status": "green",
     "detail": "312 symbols · 08:00 ET"},
    {"name": "analyst", "status": "green",
     "detail": "4 lenses · 3 signals today"},
    {"name": "portfolio_manager", "status": "green",
     "detail": "2 plans queued"},
    {"name": "compliance_officer", "status": "green",
     "detail": "0 blocks today"},
    {"name": "risk_manager", "status": "green",
     "detail": "1 resize today"},
    {"name": "executioner", "status": "amber",
     "detail": "awaiting approval"},
]

STUB_PENDING = [
    {
        "plan_id": "plan-nvda-001",
        "symbol": "NVDA",
        "direction": "long",
        "strategy": "momentum_breakout",
        "conviction": 0.74,
        "entry": 148.50,
        "stop": 146.25,
        "tp1": 153.00,
        "risk_usd": 787.50,
        "rr_tp1": 2.0,
        "ts_created": "2026-04-17T10:23:00-04:00",
        "compliance": "pass",
        "risk_result": "approve",
        "lenses": ["technical", "sentiment"]
    },
    {
        "plan_id": "plan-spy-002",
        "symbol": "SPY",
        "direction": "long",
        "strategy": "etf_sector_rotation",
        "conviction": 0.61,
        "entry": 521.40,
        "stop": 517.80,
        "tp1": 528.00,
        "risk_usd": 540.00,
        "rr_tp1": 1.8,
        "ts_created": "2026-04-17T10:31:00-04:00",
        "compliance": "pass",
        "risk_result": "resize",
        "lenses": ["technical", "macro"]
    }
]

STUB_TRADES = [
    {
        "trade_id": "tr-001",
        "symbol": "AAPL",
        "direction": "long",
        "strategy": "mean_reversion_rsi",
        "entry": 182.30,
        "exit_avg": 187.10,
        "pnl_usd": 960.00,
        "pnl_r": 1.92,
        "mfe_r": 2.3,
        "mae_r": -0.4,
        "hold_seconds": 21600,
        "exit_reason": "tp1_hit",
        "mode": "paper",
        "ts_entered": "2026-04-16T10:15:00-04:00"
    },
    {
        "trade_id": "tr-002",
        "symbol": "MSFT",
        "direction": "long",
        "strategy": "momentum_breakout",
        "entry": 415.80,
        "exit_avg": 412.40,
        "pnl_usd": -680.00,
        "pnl_r": -0.85,
        "mfe_r": 0.6,
        "mae_r": -1.1,
        "hold_seconds": 9000,
        "exit_reason": "trailing_stop_hit",
        "mode": "paper",
        "ts_entered": "2026-04-16T13:40:00-04:00"
    },
    {
        "trade_id": "tr-003",
        "symbol": "NVDA",
        "direction": "long",
        "strategy": "sentiment_catalyst",
        "entry": 138.20,
        "exit_avg": 144.80,
        "pnl_usd": 1320.00,
        "pnl_r": 2.64,
        "mfe_r": 3.1,
        "mae_r": -0.3,
        "hold_seconds": 7200,
        "exit_reason": "tp2_hit",
        "mode": "paper",
        "ts_entered": "2026-04-15T09:45:00-04:00"
    }
]
```

---

## The pending approvals screen (split layout — most important screen)

This is built in Phase 5 but design it now by adding the route stub
and template skeleton so the nav link works.

**routers/pending.py** — stub only for Phase 2:
- GET /pending → render pending.html with STUB_PENDING data
- GET /pending/{plan_id} → render pending.html with that plan selected
  (selected_plan_id in context)

**templates/pending.html** — full layout, stubbed data:

Split layout: left panel 340px fixed, right panel fills remaining width.
Both panels full viewport height minus topbar. Left panel scrollable,
right panel scrollable independently.

Left panel — "Approval queue" header with count badge:
- Each pending trade as a card (clickable, highlights active):
  - Header row: symbol (15px 500) + direction badge + time ago ("12m ago")
  - Second row: strategy tag + conviction bar (small horizontal bar,
    width = conviction %, color accent-blue)
  - Price row: Entry $xxx · Stop $xxx · TP1 $xxx
  - Risk row: Risk $xxx · R:R x.xR
  - Gate row: small pills — compliance badge (green PASS or red BLOCK) +
    risk badge (green APPROVE, amber RESIZE, red REJECT)
  - Active card: border-left 2px solid accent-blue, background slightly
    lighter than surface

Right panel — detail view for selected plan:
- Header: symbol large (24px 500) + direction badge + strategy + conviction
- TradingView chart embed (height 320px):
  Use iframe embed: https://www.tradingview.com/widgetembed/?symbol=NASDAQ:{SYMBOL}
  &interval=60&theme=dark&style=1&locale=en&hide_top_toolbar=0&hide_legend=0
  width 100%, height 320px, border 0, border-radius 8px
- Trade setup table (2 columns, clean):
  Entry | $148.50 (limit)
  Initial stop | $146.25 (hard)
  Trail activates | After +1.0R (ATR 1.5×)
  Time stop | 14:00 ET if no progress
  TP1 (50%) | $153.00 — prior resistance
  TP2 (50%) | $157.50 — measured move
  R per share | $2.25
  Position size | 350 shares
  Notional | $51,975
  Risk USD | $787.50 (0.49% equity)
  R:R to TP1 | 2.0×
  R:R to TP2 | 4.0×
- Thesis box: surface card, one-sentence summary + lenses contributing
  as small tags + similar past setups (trade_id, R outcome, similarity %)
- Evidence list: each item as a small row with type badge + ref text
- Gate results: two rows
  Compliance: green PASS + "All 8 gates passed" OR red BLOCK + reason
  Risk: green APPROVE / amber RESIZE (show original→approved size) / red REJECT
- Approval action row (bottom of right panel, sticky):
  [Approve] (green, prominent) [Reject] (red) [Modify] (neutral)
  [Approve] and [Reject] are POST /pending/{plan_id}/ack in Phase 5 stub.
  For Phase 2: show a JS confirm dialog then "Action recorded (stub)" message.
  Below buttons: "Approval expires in 14:32" countdown timer (JS, counts
  down from 15 minutes from ts_created)

If no plan selected (left panel only visible): right panel shows
"Select a trade to review" centered empty state.

---

## After Phase 2 is complete

Run the app with:
  uvicorn app:app --reload --host 0.0.0.0 --port 5000

Verify:
- [ ] Dark theme consistent across all pages
- [ ] Sidebar navigation works between all pages
- [ ] Dashboard stat cards render with stub data
- [ ] Agent status cards render
- [ ] Settings form loads and saves to settings.yaml
- [ ] Trades table renders 3 stub rows with correct formatting
- [ ] Pending screen shows split layout with left list + right detail
- [ ] TradingView chart iframe loads in pending detail
- [ ] Pending badge in sidebar shows count "2"
- [ ] ET clock updates in topbar
- [ ] HALT button shows confirmation dialog

When all items above are verified, Phase 2 is complete.
Report back with any deviations from this spec that were made during
build so CLAUDE.md can be updated.
