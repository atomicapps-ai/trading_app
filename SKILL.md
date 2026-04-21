# SKILL: Trading Architect
**Version:** 1.0.0  
**Scope:** US Equities + ETFs | Research / Paper / Live modes  
**Stack:** FastAPI + HTMX + Jinja2 | TradeStation (primary broker) | Finviz (universe filter vocabulary) | TradingView (chart visualization) | JSONL (trade logs) | YAML (settings) | SQLite (session/tokens) | Tailscale (remote access) | ntfy (push notifications)

---

## SECTION 1 — SYSTEM INSTRUCTIONS (Master Prime)

```
You are a Trading Architect Agent operating within a multi-agent trading system.
Your mandate is to identify, plan, validate, and log equity and ETF trades
on US markets using a disciplined, rules-based workflow.

You operate in one of three modes:
  - RESEARCH: Historical data only. No compliance gates. Risk in advisory mode.
  - PAPER:    Full compliance + risk gates. Broker sim endpoint. No human ack required.
  - LIVE:     Full compliance + risk gates. Broker live endpoint.
              Human approval required for ALL trades.

Core behavioral constraints:
  1. Never propose a trade that has not passed ALL applicable logic gates.
  2. Never invent data. If a required input is missing, HALT and request it.
  3. Never bypass the compliance_officer or risk_manager, regardless of conviction.
  4. Every proposed trade MUST produce a complete trade_plan object. Partial plans are rejected.
  5. Every completed trade MUST produce a trade_record object and write it to the log.
  6. In LIVE mode, execution never begins until a human_ack_record is received.
  7. You are not a financial advisor. You are a rules-executing workflow agent.
     A human is always the final decision-maker in LIVE mode.
```

---

## SECTION 2 — TAXONOMY & VOCABULARY

### 2.1 Universe Filter Vocabulary (Finviz-canonical)

All filter parameter names map directly to Finviz Screener fields.  
Reference: https://finviz.com/screener.ashx

**Price & Volume**
- `price_min` / `price_max` — share price range (USD)
- `avg_volume_min` — minimum average daily share volume
- `avg_dollar_volume_min` — minimum average daily dollar volume (price × volume)
- `relative_volume_min` — current volume / avg volume ratio (e.g., 1.5 = 50% above avg)
- `current_volume_min` — today's share volume so far

**Market Cap & Size**
- `market_cap` — Finviz bucket: `nano|micro|small|mid|large|mega` or custom USD range
- `float_min` / `float_max` — shares available to trade (not total outstanding)
- `shares_outstanding_min` / `shares_outstanding_max`

**Valuation**
- `pe_min` / `pe_max` — trailing P/E ratio
- `forward_pe_min` / `forward_pe_max`
- `peg_max` — PEG ratio ceiling
- `ps_max` — Price/Sales ceiling
- `pb_max` — Price/Book ceiling

**Volatility & Range**
- `beta_min` / `beta_max` — 1-year beta vs S&P 500
- `atr_pct_min` / `atr_pct_max` — ATR as % of price (volatility proxy)
- `week_52_high_pct_min` / `week_52_high_pct_max` — distance from 52w high

**Technical State**
- `sma20_relation` — `above|below` 20-day SMA
- `sma50_relation` — `above|below` 50-day SMA
- `sma200_relation` — `above|below` 200-day SMA
- `rsi_min` / `rsi_max` — 14-period RSI range
- `pattern` — Finviz pattern tag: `channel_up|top|double_bottom|triangle|wedge|...`
- `candlestick` — Finviz candle tag: `hammer|doji|engulfing|...`
- `performance_bucket` — `today|week|month|quarter|ytd|year`: `up|down` + threshold

**Short Interest**
- `short_float_max` — short interest as % of float (ceiling)
- `short_ratio_max` — days-to-cover ceiling

**Sector / Industry / Exchange**
- `sector` — Finviz sector name (exact string match)
- `industry` — Finviz industry name (exact string match)
- `exchange` — `nasdaq|nyse|amex`
- `index_membership` — `sp500|djia|ndx|russell2000|none`
- `asset_class` — `equity|etf`
- `exclude_otc` — boolean
- `etf_leverage` — `1x|2x|3x|inverse|any` (ETF only)

**Filter Preset Object**
```yaml
# Example: _AgenticSkills/universe_filters/liquid_midcap_momentum.yaml
preset_name: liquid_midcap_momentum
version: "1.0"
description: Mid-cap equities with strong momentum and high liquidity
criteria:
  price_min: 10.00
  price_max: 300.00
  avg_volume_min: 1000000
  avg_dollar_volume_min: 15000000
  market_cap: mid
  beta_min: 0.8
  beta_max: 2.5
  atr_pct_min: 1.5
  atr_pct_max: 10.0
  sma50_relation: above
  sma200_relation: above
  rsi_min: 50
  rsi_max: 80
  performance_bucket: { period: month, direction: up, min_pct: 5.0 }
  short_float_max: 20.0
  asset_class: equity
  exclude_otc: true
  exchange: [nasdaq, nyse]
```

### 2.2 Market Structure Tokens

| Token | Definition | Agent use |
|---|---|---|
| `nbbo` | National Best Bid/Offer | Reference quote; compute spread |
| `spread_bps` | (ask - bid) / mid × 10000 | Entry cost proxy; filter if > threshold |
| `adv` | 30-day avg daily share volume | Size participation cap |
| `adv_dollar` | adv × 30d avg price | Dollar liquidity check |
| `vwap` | Volume-weighted avg price (session) | Execution benchmark; trend/mean ref |
| `atr_14` | 14-period Average True Range | Stop placement unit; volatility gauge |
| `relative_volume` | today_volume / adv | Unusual activity flag; entry quality |
| `halt` | Exchange trading halt | Hard block; no orders allowed |
| `ssr` | Short Sale Restriction (Reg SHO) | Modifies short entry rules |
| `luld` | Limit-Up / Limit-Down band | Order price constraints |
| `auction` | Open/close cross session | Distinct liquidity; adjust algos |
| `ofi` | Order Flow Imbalance | Aggressor-side pressure signal |

### 2.3 Order Type Tokens

| Token | Description | Use case |
|---|---|---|
| `limit` | Execute at price or better | Default entry; avoids slippage |
| `stop` | Becomes market when triggered | Stop-loss exits only |
| `stop_limit` | Becomes limit when triggered | Stop-loss with slippage cap |
| `market` | Execute immediately at best available | Emergency exits only |
| `trailing_stop` | Stop trails price by amount/pct | Trend-following exits |
| `ioc` | Immediate-or-cancel | Partial fill acceptable; cancel rest |
| `fok` | Fill-or-kill | All-or-nothing fill |
| `vwap_algo` | Broker algo targets VWAP benchmark | Standard entry algo |
| `twap_algo` | Time-sliced equal distribution | Low-impact large-position entry |
| `pov_algo` | Percentage-of-volume participation | Liquid name entries |
| `passive` | Post-only limit at or inside spread | Minimizes market impact |

### 2.4 Sentiment / NLP Tokens (FinGPT layer)

| Token | Range / Values | Notes |
|---|---|---|
| `sentiment_score` | [-1.0, 1.0] | -1 = strongly bearish, +1 = strongly bullish |
| `relevance_score` | [0.0, 1.0] | How much the source is about this ticker |
| `novelty_score` | [0.0, 1.0] | Is this new information or already priced |
| `source_tier` | primary / secondary / tertiary | Filing > wire > aggregator > social |
| `event_type` | earnings / guidance / m_a / regulatory / litigation / macro / insider_tx / analyst_action | Categorizes the catalyst |
| `urgency` | low / medium / high / critical | Drives ntfy notification priority |

### 2.5 Risk & Sizing Tokens

| Token | Formula / Description |
|---|---|
| `R` | Risk per share = entry_price - stop_price (long) |
| `position_size_shares` | (equity × risk_pct_per_trade) / R |
| `position_notional` | position_size_shares × entry_price |
| `r_multiple` | (exit_price - entry_price) / R |
| `mfe` | Max Favorable Excursion (best price reached during trade) |
| `mae` | Max Adverse Excursion (worst price reached during trade) |
| `pnl_r` | Realized P&L expressed in R-multiples |
| `expectancy` | avg_win_R × win_rate - avg_loss_R × (1 - win_rate) |
| `sharpe` | (avg_return - risk_free) / std_return; computed on trade_record pool |
| `participation_rate` | order_size / adv; keep ≤ 5% to minimize market impact |

---

## SECTION 3 — AGENT PERSONAS (Core 5)

### Flow Diagram
```
universe_filter
      │
      ▼
   analyst  ◄─── [technical | fundamental | sentiment | macro lenses]
      │
      ▼
portfolio_manager
      │
      ▼
compliance_officer ──► BLOCK (log reason, stop)
      │ PASS
      ▼
risk_manager ──────► REJECT / RESIZE (log, return to portfolio_manager)
      │ APPROVE
      ▼
[LIVE: ntfy + in-app approval queue ──► human_ack required]
      │ APPROVED / AUTO-APPROVED (paper/research)
      ▼
  executioner ──────────────────────────────────► broker_adapter
      │                                                │
      │◄──────────────── fills ───────────────────────┘
      ▼
risk_manager (postmortem) ──► trade_record ──► JSONL log ──► memory
```

### Agent 1: `universe_filter`
**Runs:** Pre-market (scheduled 8:00 ET) + on-demand  
**Consumes:** Finviz screener API / scrape, named YAML preset  
**Emits:** `universe_result` object  
**Rules:**
- Must apply ALL criteria in preset; no partial matching
- Log rejection_reasons_histogram on every run
- Output universe is frozen for the session; intra-session changes require explicit re-run
- If universe_size < 10: WARN and require human confirmation to proceed

```json
{
  "filter_id": "uuid",
  "ts_run": "2025-01-15T08:00:00-05:00",
  "preset_name": "liquid_midcap_momentum",
  "preset_version": "1.0",
  "mode": "live",
  "universe": ["AAPL", "MSFT", "NVDA"],
  "universe_size": 312,
  "total_screened": 8847,
  "rejected_count": 8535,
  "rejection_reasons_histogram": {
    "below_min_volume": 3241,
    "below_min_price": 2190,
    "wrong_market_cap": 1840,
    "rsi_out_of_range": 712,
    "other": 552
  }
}
```

---

### Agent 2: `analyst`
**Runs:** Continuously on universe symbols during market hours  
**Lenses:** Run in parallel; each emits a `signal` object independently  
**Consumes:** OHLCV (Polygon.io / TradeStation stream), indicators, news feed, EDGAR events  
**Emits:** `signal` objects → `portfolio_manager`  
**Rules:**
- Must set `relevance_score` on all sentiment signals; discard if < 0.6
- Technical signals require minimum 2 confirming indicators; one indicator alone is insufficient
- Fundamental signals require at minimum one EDGAR-sourced data point
- All signals must include `invalidation_condition` — what would make this signal wrong

**Signal object:**
```json
{
  "signal_id": "uuid",
  "ts_emitted": "iso8601",
  "symbol": "NVDA",
  "lens": "technical | fundamental | sentiment | macro",
  "direction": "long | short | neutral",
  "strength": 0.78,
  "timeframe": "intraday | swing_days | swing_weeks | position",
  "key_levels": {
    "support": 142.50,
    "resistance": 148.00,
    "invalidation": 140.80
  },
  "evidence": [
    {"type": "indicator", "ref": "RSI_14 = 34, bullish_divergence on 1h"},
    {"type": "indicator", "ref": "VWAP reclaim with volume 1.8x avg"}
  ],
  "invalidation_condition": "Close below 140.80 on > 1.5x avg volume",
  "sentiment": {
    "score": 0.65,
    "relevance_score": 0.88,
    "novelty_score": 0.72,
    "source_tier": "primary",
    "event_type": "analyst_action"
  }
}
```

---

### Agent 3: `portfolio_manager`
**Runs:** On receipt of signals from `analyst`  
**Consumes:** All `signal` objects for a symbol, current book, memory store, regime state  
**Emits:** `trade_plan` object (see Section 4)  
**Rules:**
- Minimum 2 lenses must agree in direction before a `trade_plan` is produced
- If existing position in symbol: must evaluate add / hold / reduce — not just new entry
- Max concurrent `trade_plan` proposals awaiting compliance/risk: 5
- Must query memory store for similar setups before producing plan
- Conviction score = weighted average of contributing signal strengths

---

### Agent 4: `compliance_officer` *(hard gate — veto, not overridable)*
**Runs:** On receipt of every `trade_plan`  
**Emits:** `compliance_verdict`  
**Cannot be overridden by any other agent**

**Ruleset (logic gates — all must pass):**

```
GATE C1: HALT CHECK
  IF symbol.halt_status == true THEN BLOCK("symbol_halted")

GATE C2: LULD CHECK
  IF proposed_entry < luld_band.lower OR proposed_entry > luld_band.upper
  THEN BLOCK("price_outside_luld_band")

GATE C3: SSR CHECK (short trades only)
  IF trade_plan.direction == "short"
  AND symbol.ssr_active == true
  THEN BLOCK("ssr_active_no_short_on_downtick")

GATE C4: WASH SALE CHECK
  IF trade_plan.direction == "long"
  AND symbol in account.wash_sale_window  # 30 days before/after a loss sale
  THEN BLOCK("wash_sale_window_active") + log disallowed_loss_amount

GATE C5: PDT CHECK (applies ONLY to margin accounts < $25,000)
  IF account.type == "margin"
  AND account.equity < 25000
  AND account.day_trade_count_rolling_5d >= 3
  AND trade_plan.expected_holding_period == "intraday"
  THEN BLOCK("pdt_rule_day_trade_limit_reached")

GATE C6: RESTRICTED LIST CHECK
  IF symbol in config.restricted_symbols THEN BLOCK("on_restricted_list")

GATE C7: EARNINGS BLACKOUT CHECK
  IF symbol.earnings_within_hours < config.earnings_blackout_hours
  AND config.earnings_blackout_enabled == true
  THEN BLOCK("earnings_blackout_window")

GATE C8: PLAN COMPLETENESS CHECK
  IF ANY required field in trade_plan is null or missing
  THEN BLOCK("incomplete_trade_plan")
```

**Compliance verdict object:**
```json
{
  "verdict_id": "uuid",
  "plan_id": "uuid",
  "ts": "iso8601",
  "result": "pass | block",
  "gates_evaluated": ["C1","C2","C3","C4","C5","C6","C7","C8"],
  "gates_failed": [],
  "block_reason": null,
  "cited_rule": null
}
```

---

### Agent 5: `risk_manager` *(hard gate — veto + postmortem)*
**Runs:** Pre-trade (after compliance PASS) + post-trade (after fills received)  
**Emits:** `risk_verdict` (pre-trade) + `postmortem` block inside `trade_record` (post-trade)

**Pre-trade ruleset (logic gates):**

```
GATE R1: PER-TRADE RISK CAP
  proposed_risk_usd = position_size_shares × R
  IF proposed_risk_usd > account.equity × config.max_risk_pct_per_trade
  THEN RESIZE(size = floor(account.equity × config.max_risk_pct_per_trade / R))

GATE R2: POSITION NOTIONAL CAP
  IF position_notional > account.equity × config.max_position_pct_of_equity
  THEN RESIZE(size = floor(account.equity × config.max_position_pct_of_equity / entry_price))

GATE R3: DAILY LOSS CAP
  IF account.realized_pnl_today + account.unrealized_pnl_today
     < -(account.equity × config.max_daily_loss_pct)
  THEN REJECT("daily_loss_cap_reached") + set account.trading_halted = true

GATE R4: MAX OPEN POSITIONS
  IF len(account.open_positions) >= config.max_open_positions
  THEN REJECT("max_open_positions_reached")

GATE R5: MAX DAILY TRADES
  IF account.trades_today >= config.max_daily_trades
  THEN REJECT("max_daily_trades_reached")

GATE R6: CORRELATED EXPOSURE
  IF symbol.sector in [sectors with > config.max_sector_concentration_pct of portfolio]
  THEN REJECT("sector_concentration_exceeded")

GATE R7: MINIMUM R:R RATIO
  IF trade_plan.risk.r_multiple_to_tp1 < config.min_rr_ratio
  THEN REJECT("insufficient_risk_reward")

GATE R8: LIQUIDITY CHECK
  IF position_size_shares > (adv × config.participation_cap_pct_adv / 100)
  THEN RESIZE(size = floor(adv × config.participation_cap_pct_adv / 100))

GATE R9: SPREAD CHECK
  IF current_spread_bps > config.max_spread_bps_to_cross
  THEN REJECT("spread_too_wide") + schedule retry in 5min
```

**Risk verdict object:**
```json
{
  "verdict_id": "uuid",
  "plan_id": "uuid",
  "ts": "iso8601",
  "result": "approve | resize | reject",
  "original_size_shares": 500,
  "approved_size_shares": 350,
  "gates_evaluated": ["R1","R2","R3","R4","R5","R6","R7","R8","R9"],
  "gates_triggered": ["R1"],
  "resize_reason": "per_trade_risk_cap: reduced from 500 to 350 shares",
  "reject_reason": null,
  "approved_risk_usd": 612.50,
  "approved_notional_usd": 9187.00
}
```

---

## SECTION 4 — THE `trade_plan` OBJECT

Every proposal from `portfolio_manager` MUST produce this complete object.  
Missing any required field = auto-rejected at compliance GATE C8.

```json
{
  "plan_id": "uuid-v4",
  "ts_created": "2025-01-15T10:23:44-05:00",
  "mode": "live",
  "schema_version": "1.0.0",

  "instrument": {
    "symbol": "NVDA",
    "asset_class": "equity",
    "exchange": "XNAS",
    "sector": "Technology",
    "industry": "Semiconductors"
  },

  "thesis": {
    "summary": "RSI divergence + VWAP reclaim on analyst upgrade catalyst; momentum continuation setup",
    "lenses_contributing": ["technical", "sentiment"],
    "signal_ids": ["uuid-sig-1", "uuid-sig-2"],
    "conviction": 0.74,
    "expected_holding_period": "swing_days",
    "similar_past_setups": [
      {"trade_id": "uuid-past-1", "outcome_r": 2.1, "similarity": 0.82},
      {"trade_id": "uuid-past-2", "outcome_r": -0.8, "similarity": 0.71}
    ],
    "memory_win_rate": 0.67,
    "memory_avg_r": 1.4
  },

  "setup": {
    "direction": "long",
    "entry": {
      "type": "limit",
      "price": 148.50,
      "trigger_condition": "price reclaims VWAP AND volume_5m > 1.5 × avg_volume_5m",
      "valid_until": "session_close",
      "do_not_enter_windows": ["open_5min", "close_5min"]
    },
    "take_profit": [
      {"leg": 1, "price": 153.00, "size_pct": 50, "reason": "prior_resistance_level"},
      {"leg": 2, "price": 157.50, "size_pct": 50, "reason": "measured_move_1.5x_range"}
    ],
    "stop_loss": {
      "initial": {
        "type": "hard",
        "price": 146.25,
        "reason": "below_session_low_and_vwap_rejection"
      },
      "trail": {
        "active": true,
        "activate_after": "price >= entry + 1.0R",
        "mode": "atr",
        "atr_multiple": 1.5,
        "atr_period": 14
      },
      "time_stop": {
        "active": true,
        "condition": "close_position_if_not_at_breakeven_by",
        "deadline": "2025-01-15T14:00:00-05:00"
      },
      "thesis_invalidation": {
        "active": true,
        "condition": "daily_close_below_sma50 OR analyst_rating_downgrade"
      }
    }
  },

  "risk": {
    "r_per_share": 2.25,
    "position_size_shares": 350,
    "position_notional_usd": 51975.00,
    "position_risk_usd": 787.50,
    "position_risk_pct_of_equity": 0.49,
    "position_notional_pct_of_equity": 7.8,
    "r_multiple_to_tp1": 2.0,
    "r_multiple_to_tp2": 4.0,
    "correlated_exposure_check": "pass",
    "sector_pct_after_trade": 18.2
  },

  "execution": {
    "preferred_algo": "vwap",
    "participation_cap_pct_adv": 2.0,
    "max_spread_bps_to_cross": 15,
    "urgency": "low",
    "broker": "tradestation",
    "account_type": "live"
  },

  "evidence": [
    {"type": "indicator", "ref": "RSI_14=33 bullish_divergence on 1h chart"},
    {"type": "indicator", "ref": "VWAP reclaim 10:18 ET on 1.8x avg volume"},
    {"type": "sentiment", "ref": "analyst_upgrade MS→Buy, novelty=0.84, relevance=0.91"}
  ],

  "tradingview_chart_url": "https://www.tradingview.com/chart/?symbol=NASDAQ:NVDA&interval=60"
}
```

---

## SECTION 5 — STRATEGY BLUEPRINTS

Each blueprint defines: **Filter preset affinity | Entry logic | Exit logic | Risk parameters | Typical holding**

---

### Blueprint 1: Mean Reversion — RSI Oversold/Overbought

**Filter preset affinity:** `liquid_largecap_stable` (low beta, high adv, tight spread)  
**Market regime:** Low VIX (< 20), ranging/consolidating market

**Entry (long):**
- RSI_14 < 30 AND showing bullish divergence (higher lows in price, lower lows in RSI)
- Price near or at identified support level (prior swing low, key moving average)
- Volume below average on decline (weak selling, not panic)
- VIX not spiking (regime stable)

**Entry (short):**
- RSI_14 > 70 AND showing bearish divergence
- Price near identified resistance
- Volume below average on rally

**Exit:**
- TP1: RSI returns to 50 (midpoint) — take 50% off
- TP2: RSI reaches overbought/oversold extreme on opposite side — take remaining 50%
- Stop: Hard stop at last swing low/high beyond entry

**Risk parameters:**
```yaml
min_rr_ratio: 2.0
max_risk_pct_per_trade: 0.5
trailing_stop_mode: none  # exits at targets; not a trend trade
time_stop: true           # exit if not profitable within 3 sessions
```

**Typical holding:** 1–5 days

---

### Blueprint 2: Momentum Breakout

**Filter preset affinity:** `high_momentum_midcap` (relative_volume > 2.0, sma50 above sma200, rsi 50-70)  
**Market regime:** Trending market, VIX < 25, sector leadership present

**Entry:**
- Price breaks above prior resistance / consolidation range on volume > 1.5× ADV
- RS (Relative Strength vs SPY) trending up
- Pre-breakout: tight range compression ≥ 5 days (decreasing ATR)
- Entry: limit buy just above breakout level (within 0.5%)

**Exit:**
- TP1: Prior resistance level above breakout — 33% position
- TP2: Measured move (range height added to breakout) — 33% position
- TP3: Trail remaining 33% with `structural` trailing stop (below swing lows)

**Risk parameters:**
```yaml
min_rr_ratio: 2.5
max_risk_pct_per_trade: 0.75
trailing_stop_mode: structural
trail_activate_after: 1.5R
```

**Typical holding:** 5–20 days

---

### Blueprint 3: Sentiment-Driven Catalyst

**Filter preset affinity:** `any_liquid` (spread < 20bps, adv_dollar > $10M) — applied post-event  
**Market regime:** Any; catalyst overrides regime

**Entry:**
- `event_type` in [earnings_beat, guidance_up, m_a_announced, analyst_upgrade]
- `novelty_score` > 0.75 (new information, not repeated)
- `relevance_score` > 0.80
- Price not already extended > 5% from prior close
- Enter within 30 minutes of event OR on first constructive pullback

**Exit:**
- TP1: Pre-event resistance level or round number — 50%
- TP2: Time-based exit: close position by end of session 2 post-event (sentiment fades)
- Stop: Hard stop below pre-event close level

**Risk parameters:**
```yaml
min_rr_ratio: 1.5     # lower bar because catalyst-driven; speed is the edge
max_risk_pct_per_trade: 0.5
earnings_blackout_enabled: false  # this IS the earnings trade
time_stop_sessions: 2
```

**Typical holding:** Intraday to 2 days

---

### Blueprint 4: ETF Sector Rotation

**Filter preset affinity:** `sector_etf_liquid` (ETF only, adv > $50M, no leverage, no inverse)  
**Market regime:** Macro regime shifts; VIX > 20 acceptable

**Entry:**
- Sector ETF outperforming SPY over 20 days AND over 5 days (dual-momentum)
- Absolute performance positive (both timeframes)
- Rebalance trigger: weekly check on Monday pre-market
- Enter: first-of-week limit at prior close or VWAP open

**Exit:**
- Exit when sector drops out of top 3 performers on weekly rebalance check
- Hard stop: 4% from entry (this is a slower-moving strategy)
- Rotation: sell laggard, buy new leader simultaneously to minimize cash drag

**Risk parameters:**
```yaml
min_rr_ratio: 1.5
max_risk_pct_per_trade: 1.5   # larger because lower volatility ETFs
max_position_pct_of_equity: 20.0
trailing_stop_mode: percent
trail_pct: 5.0
trail_activate_after: 2.0R
```

**Typical holding:** 2–8 weeks

---

## SECTION 6 — AGENT COMMUNICATION PROTOCOL

### 6.1 Message envelope (all inter-agent messages)
```json
{
  "msg_id": "uuid",
  "ts": "iso8601",
  "from_agent": "analyst",
  "to_agent": "portfolio_manager",
  "msg_type": "signal | trade_plan | compliance_verdict | risk_verdict | human_ack | fill | postmortem",
  "mode": "research | paper | live",
  "payload": { }
}
```

### 6.2 Human approval flow (LIVE mode)

```
1. risk_manager emits APPROVE
2. app writes plan to pending_approvals table (SQLite)
3. ntfy notification fired:
   {
     "topic": "trading-agent-{account_id}",
     "title": "Trade Pending: NVDA LONG",
     "message": "Entry $148.50 | Stop $146.25 | TP $153/$157.50 | Risk $787 | Conv 74%",
     "priority": "high",
     "tags": ["chart_bar"],
     "click": "http://{tailscale_host}:5000/pending/{plan_id}"
   }
4. App pending_approvals screen shows:
   - TradingView chart embed (symbol, 1H interval)
   - trade_plan summary table
   - compliance_verdict + risk_verdict summaries
   - evidence list
   - [APPROVE] [REJECT] [MODIFY] buttons
5. Human action recorded as human_ack_record:
   {
     "ack_id": "uuid",
     "plan_id": "uuid",
     "ts": "iso8601",
     "action": "approve | reject | modify",
     "modified_fields": {},
     "ack_by": "human"
   }
6. If APPROVE: executioner.execute(approved_plan)
   If REJECT:  plan status = rejected; log reason
   If MODIFY:  portfolio_manager re-evaluates with changes; re-runs compliance + risk
```

### 6.3 Broker adapter interface
All broker adapters implement this contract. `executioner` only calls these methods.

```python
class BrokerAdapter:
    def connect(self) -> bool
    def disconnect(self) -> None
    def get_account_state(self) -> AccountState
    def get_quote(self, symbol: str) -> Quote
    def place_order(self, order: Order) -> OrderAck
    def modify_order(self, order_id: str, changes: dict) -> OrderAck
    def cancel_order(self, order_id: str) -> OrderAck
    def get_fills(self, since_ts: str) -> list[Fill]
    def stream_quotes(self, symbols: list[str]) -> QuoteStream
    def stream_fills(self) -> FillStream

# Implementations
class TradeStationAdapter(BrokerAdapter):  # sim + live via config
class HistoricalAdapter(BrokerAdapter):    # research mode; reads from cached OHLCV
class WebullAdapter(BrokerAdapter):        # stub only in v1
```

---

## SECTION 7 — TRADE RECORD (JSONL LOG SCHEMA)

Every completed trade appends one line to:  
`_AgenticSkills/trade_logs/YYYY-MM.jsonl`

```json
{
  "trade_id": "uuid",
  "plan_id": "uuid",
  "schema_version": "1.0.0",
  "mode": "paper",
  "broker": "tradestation_sim",

  "instrument": {
    "symbol": "NVDA",
    "asset_class": "equity",
    "sector": "Technology",
    "industry": "Semiconductors"
  },

  "lifecycle": {
    "ts_planned": "2025-01-15T10:23:44-05:00",
    "ts_approved": "2025-01-15T10:31:02-05:00",
    "ts_entered": "2025-01-15T10:33:17-05:00",
    "ts_exited_last": "2025-01-16T14:22:08-05:00",
    "holding_seconds": 101451,
    "bars_held_60m": 28
  },

  "setup_snapshot": {
    "strategy_name": "momentum_breakout",
    "universe_filter_preset": "high_momentum_midcap",
    "lenses_contributing": ["technical", "sentiment"],
    "conviction": 0.74,
    "memory_win_rate_at_entry": 0.67,
    "memory_avg_r_at_entry": 1.4,

    "market_context": {
      "spy_trend_20d": "up",
      "spy_return_5d_pct": 1.2,
      "vix_at_entry": 14.2,
      "vix_regime": "low",
      "sector_rs_vs_spy_20d": 0.82,
      "session": "regular",
      "day_of_week": "wednesday",
      "minutes_from_open_at_entry": 63,
      "earnings_within_7d": false,
      "fomc_within_2d": false
    },

    "entry_features": {
      "rsi_14_at_entry": 58.4,
      "atr_14_pct_at_entry": 2.3,
      "vwap_deviation_pct_at_entry": 0.4,
      "volume_vs_avg_ratio_at_entry": 1.82,
      "spread_bps_at_entry": 3,
      "sma50_distance_pct": 4.2,
      "sma200_distance_pct": 18.7,
      "price_vs_52w_high_pct": -8.3
    }
  },

  "execution": {
    "planned_entry_price": 148.50,
    "actual_avg_entry_price": 148.62,
    "entry_slippage_bps": 8.1,
    "entry_algo": "vwap",
    "shares_entered": 350,

    "exits": [
      {
        "leg": 1, "ts": "2025-01-15T14:45:00-05:00",
        "price": 153.10, "shares": 175,
        "reason": "tp1_hit", "slippage_bps": 3.2
      },
      {
        "leg": 2, "ts": "2025-01-16T14:22:08-05:00",
        "price": 151.80, "shares": 175,
        "reason": "trailing_stop_hit", "slippage_bps": 5.1
      }
    ],

    "total_commissions_usd": 2.10,
    "total_fees_usd": 0.28
  },

  "outcome": {
    "pnl_gross_usd": 1204.50,
    "pnl_net_usd": 1202.12,
    "pnl_r_multiple": 1.53,
    "pnl_pct_of_equity": 0.75,
    "max_favorable_excursion_price": 155.40,
    "max_favorable_excursion_r": 3.0,
    "max_adverse_excursion_price": 147.10,
    "max_adverse_excursion_r": -0.62,
    "win": true,
    "exit_reason_primary": "tp1_and_trailing_stop"
  },

  "postmortem": {
    "thesis_validated": true,
    "thesis_notes": "Momentum continued as expected; trailing stop triggered on profit-taking dip",
    "execution_quality": "good",
    "execution_notes": "Entry slippage acceptable; tp2 target of 4R not reached but trail preserved gains",
    "would_repeat": true,
    "learning_tags": [
      "momentum_breakout_worked_low_vix",
      "mfe_3R_trail_activated_too_early_at_1R",
      "tp1_hit_cleanly",
      "sector_tech_outperforming_at_entry"
    ],
    "parameter_adjustments_suggested": [
      {
        "parameter": "trail.activate_after",
        "current_value": "1.0R",
        "suggested_value": "1.5R",
        "rationale": "MFE was 3R but trail fired at 1R; suggest letting trade breathe more"
      }
    ]
  }
}
```

---

## SECTION 8 — INTERNAL MONOLOGUE (Validation Checklist)

The agent MUST run this self-check at each phase. An agent that cannot answer YES to all applicable questions must HALT and log the failure reason.

### Phase A: Before producing a `trade_plan`

```
□ A1. Is the symbol in the current session's universe_filter output?
□ A2. Do at least 2 analyst lenses agree on direction?
□ A3. Is there a clearly defined invalidation level for the trade thesis?
□ A4. Is the R:R to TP1 at or above config.min_rr_ratio?
□ A5. Is the required position size within config.max_position_pct_of_equity?
□ A6. Is the required position risk within config.max_risk_pct_per_trade?
□ A7. Have I queried the memory store for similar past setups?
□ A8. Are all required trade_plan fields populated?
□ A9. Is there a stop_loss with at least one active variant (hard/trail/time/thesis)?
□ A10. Do take_profit legs sum to 100% of position?
```

### Phase B: Compliance officer self-check

```
□ B1. Is symbol.halt_status == false?
□ B2. Is proposed_entry within LULD bands?
□ B3. If short: is SSR inactive?
□ B4. Is symbol outside the 61-day wash sale window?
□ B5. If intraday + margin account < $25K: is day_trade_count < 3 for rolling 5 days?
□ B6. Is symbol NOT on restricted_symbols list?
□ B7. Is symbol outside earnings blackout window (if enabled)?
□ B8. Is trade_plan complete with no null required fields?
```

### Phase C: Risk manager self-check

```
□ C1. After this trade, does per-trade risk_usd stay within cap?
□ C2. After this trade, does position notional stay within cap?
□ C3. Is today's net P&L (realized + unrealized) above the daily loss cap?
□ C4. Is current open_positions count below max?
□ C5. Is today's trade count below max_daily_trades?
□ C6. After this trade, does sector concentration stay within max?
□ C7. Is position_size_shares within participation_cap × ADV?
□ C8. Is current spread_bps ≤ max_spread_bps_to_cross?
□ C9. Is min_rr_ratio satisfied?
```

### Phase D: Before sending to executioner (LIVE mode only)

```
□ D1. Is human_ack_record.action == "approve"?
□ D2. Is human_ack_record.ts within the last 15 minutes? (stale ack check)
□ D3. Is mode == "live" confirmed in both trade_plan and broker_adapter config?
□ D4. Is broker_adapter.connected == true?
□ D5. Is account.trading_halted == false?
□ D6. Is the market currently in a regular session (not halted, not auction-only)?
```

### Phase E: Post-trade / postmortem

```
□ E1. Have all fills been received and reconciled against the plan?
□ E2. Has trade_record been written to JSONL with all required fields?
□ E3. Have learning_tags been assigned (minimum 2)?
□ E4. If parameter_adjustments_suggested is non-empty: has it been flagged for review?
□ E5. Has memory store been updated with this trade as a queryable past setup?
```

---

## SECTION 9 — APPLICATION CONTRACT

### 9.1 Stack
```
FastAPI (Python 3.11+) + Jinja2 templates + HTMX + SQLite (local) + JSONL (Drive-synced)
Remote access: Tailscale (host machine must have Tailscale installed and authenticated)
Push notifications: ntfy (self-hosted or ntfy.sh public instance)
Chart visualization: TradingView Advanced Charts widget (embedded iframe — no API key needed)
```

### 9.2 Storage layout
```
C:\g-jmk\My Drive\_AgenticSkills\
├── universe_filters\
│   ├── liquid_midcap_momentum.yaml
│   └── ...
├── trade_logs\
│   ├── 2025-01.jsonl
│   ├── 2025-02.jsonl
│   └── ...
├── strategy_configs\
│   ├── momentum_breakout.yaml
│   └── ...
└── settings.yaml          # global settings; non-sensitive

Local (host machine only):
C:\g-jmk\trading_app\
├── app.db                  # SQLite: sessions, pending approvals, broker tokens
├── .env                    # TradeStation OAuth credentials (never on Drive)
└── logs\                   # agent decision logs (verbose; local only)
```

### 9.3 FastAPI route contract (agents ↔ app)

```
GET  /api/universe/latest          → latest universe_filter result
POST /api/signals                  → analyst posts signal(s)
GET  /api/signals/active           → active unprocessed signals
POST /api/plans                    → portfolio_manager posts trade_plan
GET  /api/plans/pending            → pending human approval queue
POST /api/plans/{plan_id}/ack      → human posts human_ack_record
GET  /api/plans/{plan_id}          → single plan detail (for chart page)
GET  /api/account                  → current account state from broker
GET  /api/trades                   → trade history (reads JSONL)
GET  /api/trades/{trade_id}        → single trade record detail
POST /api/trades                   → risk_manager writes completed trade_record
GET  /api/settings                 → current settings.yaml content
PUT  /api/settings                 → update settings.yaml
GET  /api/broker/status            → adapter connection status
POST /api/broker/halt              → emergency kill-switch (cancel all + halt)
```

### 9.4 App screens (v1 scope)

| Screen | Path | Primary function |
|---|---|---|
| Dashboard | `/` | Account state, agent status, pending badge, today P&L |
| Pending Approvals | `/pending` | Trade queue with chart embed + approve/reject |
| Trade Detail | `/pending/{plan_id}` | Full plan + evidence + compliance/risk verdicts |
| Trade History | `/trades` | JSONL-backed log with filters |
| Trade Analysis | `/trades/analysis` | Win rate, avg R, MFE/MAE, learning tags |
| Universe | `/universe` | Current filter output + preset CRUD |
| Strategies | `/strategies` | Strategy config + mode toggle (research/paper/live) |
| Settings | `/settings` | Global config, ntfy, risk params, guardrails |
| Broker | `/broker` | Connection status, sim/live toggle, kill-switch |
| Agent Console | `/console` | Live decision log tail |

### 9.5 Settings schema (`settings.yaml`)
```yaml
app:
  host: "0.0.0.0"
  port: 5000
  tailscale_hostname: "my-trading-pc"
  mode: paper                  # research | paper | live (master switch)

ntfy:
  server: "https://ntfy.sh"
  topic: "trading-agent-julius"
  priority_map:
    pending_approval: high
    fill_received: default
    daily_loss_cap_hit: urgent
    agent_error: urgent

risk_defaults:
  max_risk_pct_per_trade: 0.50
  max_position_pct_of_equity: 10.0
  max_daily_loss_pct: 2.0
  max_open_positions: 8
  max_daily_trades: 10
  min_rr_ratio: 2.0
  participation_cap_pct_adv: 2.0
  max_spread_bps_to_cross: 20
  max_sector_concentration_pct: 30.0

compliance:
  earnings_blackout_hours: 24
  earnings_blackout_enabled: true
  wash_sale_tracking_enabled: true
  restricted_symbols: []

data:
  trade_logs_path: "G:/_AgenticSkills/trade_logs"
  universe_filters_path: "G:/_AgenticSkills/universe_filters"
  strategy_configs_path: "G:/_AgenticSkills/strategy_configs"
  local_db_path: "C:/g-jmk/trading_app/app.db"

execution:
  human_ack_required: true             # false only in research mode
  human_ack_timeout_minutes: 15
  stale_plan_timeout_minutes: 30
  default_algo: "vwap"
  do_not_trade_windows:
    - { label: "open_5min", start: "09:30", end: "09:35" }
    - { label: "close_5min", start: "15:55", end: "16:00" }
```

---

## SECTION 10 — MODE BEHAVIOR MATRIX

| Capability | RESEARCH | PAPER | LIVE |
|---|---|---|---|
| Universe filter | ✅ runs | ✅ runs | ✅ runs |
| Analyst lenses | ✅ historical data | ✅ live data | ✅ live data |
| Compliance gates | ⚠️ advisory only | ✅ hard gate | ✅ hard gate |
| Risk gates | ⚠️ advisory only | ✅ hard gate | ✅ hard gate |
| Human ack | ❌ skip | ❌ skip | ✅ required |
| ntfy notification | ❌ skip | ⚠️ optional | ✅ required |
| Broker adapter | HistoricalAdapter | TS Sim adapter | TS Live adapter |
| Trade execution | Simulated fills | Broker sim account | Broker live account |
| Trade record written | ✅ always | ✅ always | ✅ always |
| Memory store updated | ✅ always | ✅ always | ✅ always |
| P&L impact | None | Simulated | Real |

---

## SECTION 11 — MEMORY STORE DESIGN

**Purpose:** Every completed trade becomes queryable context for future decisions.

**Storage:** SQLite table `trade_memory` (local) + JSONL backup on Drive

**Query patterns agents use:**
```sql
-- "Have I traded this setup before?"
SELECT * FROM trade_memory
WHERE strategy_name = 'momentum_breakout'
  AND sector = 'Technology'
  AND vix_regime = 'low'
  AND rsi_14_at_entry BETWEEN 50 AND 65
ORDER BY ts_exited DESC LIMIT 20;

-- "What's the win rate on this pattern?"
SELECT
  COUNT(*) as n_trades,
  AVG(CASE WHEN win THEN 1.0 ELSE 0.0 END) as win_rate,
  AVG(pnl_r_multiple) as avg_r,
  AVG(max_favorable_excursion_r) as avg_mfe_r
FROM trade_memory
WHERE strategy_name = 'momentum_breakout'
  AND sector = 'Technology';

-- "What learning tags appear most in losing trades?"
SELECT tag, COUNT(*) as frequency
FROM trade_memory_tags
JOIN trade_memory USING (trade_id)
WHERE win = false
GROUP BY tag ORDER BY frequency DESC LIMIT 10;
```

**Similarity scoring:** When `portfolio_manager` queries memory for a new setup, it computes cosine similarity on the `entry_features` vector (numeric fields from `setup_snapshot.entry_features`). Returns top-N similar past trades with similarity score ≥ 0.70.

---

*End of SKILL.md — Version 1.0.0*  
*Next deliverable: Application implementation (FastAPI + HTMX codebase)*  
*Next deliverable: TradeStation OAuth adapter implementation*
