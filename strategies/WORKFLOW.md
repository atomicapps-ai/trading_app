# Strategy Discovery Workflow — End-to-End

**Last updated:** 2026-05-09 · run on a Windows box, single Python process

This is the full pipeline that turns raw price bars into validated strategy
candidates. Each stage is resumable, persists everything, and is queryable
with SQL after the fact.

---

## Pipeline diagram

```
                     ┌─────────────────────────────────────────────────┐
                     │ 1. UNIVERSE SELECTION                            │
                     │    Finviz screener → ticker list                 │
                     └─────────────────────────────────────────────────┘
                                          │
                                          ▼
                     ┌─────────────────────────────────────────────────┐
                     │ 2. BAR DATA FETCH                                │
                     │    HF (stocks) / yfinance (ETFs) / Alpaca (30m)  │
                     │    → data/historical/{SYM}_{interval}.csv        │
                     └─────────────────────────────────────────────────┘
                                          │
                                          ▼
                     ┌─────────────────────────────────────────────────┐
                     │ 3. RANDOM SEARCH                                 │
                     │    sample meta-strategy config, run, score       │
                     │    × IS (in-sample) and OOS (out-of-sample)      │
                     │    → random_search_trials (one row per trial)    │
                     └─────────────────────────────────────────────────┘
                                          │
                                          ▼
                     ┌─────────────────────────────────────────────────┐
                     │ 4. VECTOR ANALYSIS                               │
                     │    SQL queries → IC tables, archetype clusters   │
                     │    → strategies/VECTOR_ANALYSIS.md               │
                     └─────────────────────────────────────────────────┘
                                          │
                                          ▼
                     ┌─────────────────────────────────────────────────┐
                     │ 5. ARCHETYPE INSPECTION                          │
                     │    re-run top trials, dump trade ledger          │
                     │    long/short split, holding periods, exit mix   │
                     └─────────────────────────────────────────────────┘
                                          │
                                          ▼
                     ┌─────────────────────────────────────────────────┐
                     │ 6. HOLD-OUT VALIDATION (next phase)              │
                     │    repeat 1-3 on a fresh universe                │
                     │    reject anything whose edge doesn't transfer   │
                     └─────────────────────────────────────────────────┘
```

---

## Stage 1 — Universe selection

**Tool:** Finviz screener via `services/universe_service.scrape_finviz_filters`

**Config:** filter dict like:
```python
{
    "sh_price": "o10",                # price > $10
    "sh_avgvol": "o2000",             # avg vol > 2M shares/day
    "ta_averagetruerange": "o3",      # daily ATR > $3 USD
}
```

**Storage:**
- SQLite: `data/claude_trading_app.db::universe_presets` — full screener config + ticker list
- Git: `universe_screeners.yaml` — auto-exported on every CRUD so the screener config is versioned

**Why screener-driven:** instead of hand-picking 16 names, we let an objective filter decide what's in the universe. The current `high_atr_liquid` screener returns ~300 names that are liquid enough to trade and volatile enough to actually move.

**Run it:**
```
python scripts/create_high_atr_screener.py
```

---

## Stage 2 — Bar data fetch

**Tools:**
- `services/hf_data_service.py` — three sources (HF parquet, yfinance, Alpaca)
- `scripts/bulk_fetch_screener.py` — walks every ticker in a screener, skips already-cached

**File format:** `data/historical/{SYMBOL}_{interval}.csv` with columns
`Date,Open,High,Low,Close,Volume`. UTC timestamps. RTH-only for intraday.

**Source selection:**
| Source | Use when | Speed |
|---|---|---|
| HF stocks-daily-price | US stocks, daily, no auth | ~5s/symbol after first stream |
| yfinance | ETFs, indices, foreign tickers | ~1s/symbol |
| Alpaca | Need 5+ years of intraday | ~10s/symbol |

**Run it:**
```
python scripts/bulk_fetch_screener.py --screener high_atr_liquid --source auto --interval 1d
```

---

## Stage 3 — Random search (the heart of it)

**Tool:** `scripts/random_search.py` + `agents/detectors/external/meta_strategy.py`

### What a "meta-strategy" is

A single parameterized detector that, depending on its config, can express
any of these strategies:

| Block | Choices |
|---|---|
| Entry primitive | `atr_band` / `bb_extreme` / `rsi_extreme` / `macd_zero_cross` / `n_day_breakout` |
| Regime filters (any subset) | `long_ma_filter`, `adx_filter`, `vol_pct_filter` |
| Volume filter | on/off + (lookback, mult) |
| Stop type | `atr_mult` / `opposite_band` / `fixed_pct` |
| TP type | `r_multiple_single` / `mean_revert` / `time_only` |
| Time stop | 20-250 bars |
| Long-only | on/off |

Plus 20+ continuous params (RSI thresholds, MA lengths, ATR multipliers, etc.).
**The whole space has billions of points** — too many to grid search.

### What random search does (per trial)

1. **Sample** one config from the design space (uniform random per param)
2. **Pick** one symbol from the universe
3. **Load** that symbol's full bar history (cached, no I/O most of the time)
4. **Split** into IS (2010-2024) and OOS (2025-2026)
5. **Run** `meta_strategy.detect(bars, cfg)` → list of Signals (long/short)
6. **Simulate** each signal through `simulate_trades(bars, signals)` →
   list of Trades with stop/TP/time-stop exits
7. **Score** the trades on full window, IS-only, and OOS-only
8. **Persist** the row to `random_search_trials`

A single trial takes ~150-200ms. The engine commits in batches of 50 to
amortize SQLite transaction overhead, achieving ~5 trials/sec sustained.

### What gets stored per trial

The `random_search_trials` row captures:

```
trial_id              uuid
symbol                AAPL, NVDA, etc.
bars_interval         '1d' or '30m'
meta_config_json      full config (entry, filters, stops, all params)
entry_primitive       extracted for fast SQL grouping
stop_type             ditto
tp_type               ditto
regime_filter_count   # of active filters (selectivity proxy)
uses_volume_filter    0 or 1
n_trades              total trade count over full window
wr_pct                win rate %
profit_factor         gross_profit / gross_loss
net_pnl_usd           on $10k/trade
avg_r_multiple        signed R-multiples averaged
max_drawdown_pct      peak-to-trough on equity curve
score                 composite: (PF-1) × log(N) × WR%/100
is_score              same composite, computed on IS bars only
oos_score             same, OOS only
is_oos_gap_pct        (is_score - oos_score) / is_score — overfit detector
feature_vector_json   symbol class, vol regime, trend regime, etc.
ran_at                ISO-8601 timestamp
duration_ms           per-trial wall time
window_start          first bar date in test
window_end            last bar date in test
```

The two-window IS/OOS scoring is the key innovation. A trial that scores
2.0 in-sample but -0.5 out-of-sample is overfit and rejected. A trial
that scores 2.0 IS and 1.8 OOS is real.

### Run it

```bash
# 16 symbols × 2000 trials = 32k trials, ~2 hours
python scripts/random_search.py --trials-per-symbol 2000 --interval 1d

# 300 symbols × 500 trials = 150k trials, ~8 hours
python scripts/random_search.py --screener high_atr_liquid --trials-per-symbol 500

# Run forever (multi-day collection)
python scripts/random_search.py --screener high_atr_liquid --forever
```

Resumable: kill the process at any time, re-run with the same args, it
picks up where it left off (counts existing trials per symbol).

---

## Stage 4 — Vector analysis

**Tool:** `scripts/vector_analyze.py`

Produces:
1. **Information coefficient table** — Spearman rank correlation between
   each numeric param and `score`, then again vs `oos_score`. Tells us
   which knobs actually matter.
2. **Categorical config rankings** — for each entry primitive / stop / TP
   choice, mean & median score across eligible trials.
3. **OOS-robust archetypes** — top-50 trials filtered by:
   - PF > 1
   - N ≥ 30 trades
   - oos_score > 0
   - |is_oos_gap_pct| ≤ 0.5 (no more than 50% IS-vs-OOS divergence)
4. **Top-20 individual configs** with full readable spec strings

Output: `strategies/VECTOR_ANALYSIS.md` (markdown, regenerates on each run).

---

## Stage 5 — Archetype inspection

**Tool:** `scripts/inspect_top_archetype.py`

Takes the top-5 OOS-robust archetypes, re-runs them with the exact same
config, and prints the **full trade ledger**:
- Long/short split per trial
- Win rate per direction
- Exit reason distribution (stop / tp / time_stop / opposite_signal / end_of_data)
- Average win % vs average loss %
- Average bars held
- First and last 3 trades of each (sanity check that it's not just one regime)

This is where you catch mistakes the score didn't see — e.g. "100% of trades
are stop-outs at -3%" or "all trades are in 2023, none in 2024-2026".

---

## Stage 6 — Hold-out validation (planned next)

The bellwether-16 universe was reverse-engineered from one strategy's
backtest, so any winners are at risk of survivorship bias. The next phase:

1. Pick 16-30 fresh symbols the strategies have never seen (e.g. JPM, V, KO,
   JNJ, WMT, KO, PEP, T, VZ, MCD, etc.)
2. Run the top 5 archetypes from random search on those names
3. Anything whose performance survives is real

The screener-based approach (`high_atr_liquid`, 300 names) already partly
addresses this — the universe is now objective-filter-defined, not
strategy-defined.

---

## What's in the database

Single SQLite file at `data/optimization_results.db`. Tables:

| Table | Rows now | Rows after a long run | Purpose |
|---|---|---|---|
| `optimization_runs` | ~12,000 | same | Phase C grid sweep results |
| `param_reasoning` | ~48,000 | same | Per-param "why this value" text |
| `best_per_symbol` | ~48 | same | Phase C winners |
| `random_search_trials` | ~12,000 | 100k-500k | Phase F trials |
| `analysis_log` | a few | a few hundred | Findings + warnings |
| `optimizer_checkpoints` | per-pair | same | Resume markers |

**Querying it** is just SQL. Examples:

```sql
-- Top 10 OOS-robust trials across the universe
SELECT symbol, entry_primitive, stop_type, tp_type,
       n_trades, wr_pct, profit_factor, oos_score
FROM random_search_trials
WHERE n_trades >= 50 AND profit_factor > 1.5
  AND ABS(is_oos_gap_pct) <= 0.3
ORDER BY oos_score DESC LIMIT 10;

-- Best entry primitive per symbol class
SELECT json_extract(feature_vector_json, '$.symbol_class') AS symbol_class,
       entry_primitive,
       AVG(score) AS avg_score,
       COUNT(*) AS n
FROM random_search_trials
WHERE n_trades >= 30 AND profit_factor > 1.0
GROUP BY symbol_class, entry_primitive
ORDER BY symbol_class, avg_score DESC;

-- How does score change with regime filter count?
SELECT regime_filter_count,
       COUNT(*) AS n,
       ROUND(AVG(score), 3) AS avg_score,
       ROUND(AVG(oos_score), 3) AS avg_oos
FROM random_search_trials
WHERE n_trades >= 30
GROUP BY regime_filter_count
ORDER BY regime_filter_count;
```

The DB is the long-term asset. Multi-day collection accumulates hundreds
of thousands of trials, then any question is a query away.

---

## Complete commands cheat sheet

```bash
# 1. Create / refresh the screener and scrape Finviz
python scripts/create_high_atr_screener.py

# 2. Bulk fetch daily bars for new tickers (skips already-cached)
python scripts/bulk_fetch_screener.py --screener high_atr_liquid

# 3. Long-running random search on the expanded universe
python scripts/random_search.py --screener high_atr_liquid --forever

# 4. Run analysis (any time, even mid-run)
python scripts/vector_analyze.py

# 5. Inspect the top trials with full trade ledgers
python scripts/inspect_top_archetype.py

# 6. Resume after kill / restart
# (just re-run the same random_search command — it counts existing rows)
```
