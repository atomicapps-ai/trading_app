# Random Search Engine — Design Doc

**Status:** in development · **Created:** 2026-05-09

## Why random search

Grid sweep (Phase C) hit its ceiling at ~12k combos because:
1. Each strategy's grid is hand-picked by me (biased)
2. Combinatorial growth: 4 params × 5 values each = 625 combos per strategy
3. No way to add cross-strategy primitives (e.g. "MACD entry + ATR stop + volume filter")

Random search wins past ~5 params because it samples the space more
efficiently than grid (Bergstra & Bengio 2012, "Random Search for
Hyper-Parameter Optimization"). It also lets us define a SUPERSET of
features and let the optimizer tell us which subset matters.

## The meta-strategy

One "meta-strategy" config picks one option from each of these blocks.
The random sampler picks values uniformly per parameter; categorical
choices are uniform over enums.

### Block 1 — Entry primitive (pick one)
| ID | Description | Params |
|---|---|---|
| `atr_band` | Cross of price/MA over ATR-trailed band (PMax/SuperTrend family) | `atr_period`, `atr_mult`, `ma_length`, `ma_type` |
| `bb_extreme` | Close crosses opposite-side Bollinger band (mean-rev) | `bb_length`, `bb_mult` |
| `rsi_extreme` | RSI cross from oversold/overbought zone | `rsi_length`, `rsi_lo`, `rsi_hi` |
| `macd_zero_cross` | MACD histogram cross of 0 with line in correct half | `macd_fast`, `macd_slow`, `macd_signal` |
| `n_day_breakout` | Close breaks N-day high/low | `breakout_length` |
| `gap_continuation` | Day opens with gap > X% in trend direction | `gap_min_pct` |
| `vwap_reclaim` | Close crosses back through session VWAP after extending the other way | (intraday only) |

### Block 2 — Regime filters (any subset, on/off independently)
| ID | When active, requires | Params |
|---|---|---|
| `long_ma_filter` | Close > SMA(N) for longs, < for shorts | `regime_ma_length` |
| `vix_threshold` | Prior-day VIX close in range | `vix_min`, `vix_max` |
| `adx_filter` | ADX(14) above OR below threshold | `adx_min`, `adx_max` |
| `volatility_percentile` | Realized 20-day vol in N-th percentile of prior year | `vol_percentile_min`, `vol_percentile_max` |
| `relative_strength` | Symbol's 20-day return vs SPY's 20-day return | `rs_min`, `rs_max` |
| `time_of_year` | Calendar month restriction | `months_allowed` (bitmask) |

### Block 3 — Volume filter (optional)
| ID | Description | Params |
|---|---|---|
| `volume_min_mult` | Current bar's volume ≥ X × N-day median | `vol_lookback`, `vol_mult` |
| `up_volume_share` | Up-volume / total-volume over 60 bars > threshold | `up_vol_threshold` |
| (off) | No volume filter | — |

### Block 4 — Stop type (pick one)
| ID | Description | Params |
|---|---|---|
| `atr_mult` | Stop = entry ± `stop_atr_mult` × ATR(14) | `stop_atr_mult` |
| `opposite_band` | Stop = the opposite signal band | (none) |
| `fixed_pct` | Stop = entry ± X% | `stop_pct` |
| `recent_swing` | Stop = lowest low / highest high of last N bars | `swing_lookback` |

### Block 5 — TP type (pick one)
| ID | Description | Params |
|---|---|---|
| `r_multiple_single` | Single TP at entry + N × R | `tp_r_multiple` |
| `r_multiple_legged` | TP1 at 2R (close 50%), TP2 at 4R | (preset) |
| `mean_revert` | TP = SMA(N), the basis line | `tp_ma_length` |
| `time_only` | No TP, exit at time stop | — |

### Block 6 — Exit overlay (always on)
- `time_stop_bars`: int 20-200 (uniform sample)
- `trail_to_be_at_r`: continuous 0.0-1.0 (when 0, trail-to-BE is OFF)

## Feature columns added per trial

For every trial, alongside params and outcome, store these features so
later vector analysis can answer "what works when X":

```sql
ALTER TABLE optimization_runs ADD COLUMN feature_vector_json TEXT;
```

Where `feature_vector_json` includes:

| Feature | Source | Why |
|---|---|---|
| `symbol_class` | hand-mapped (tech/defensive/index/financial) | The biggest split in current findings |
| `symbol_avg_atr_pct` | mean(ATR/close) over the test window | Volatility character |
| `symbol_trend_regime_pct` | % of test bars where close > SMA(200) | Bull-bias of the symbol |
| `symbol_yoy_return` | total return over the test window | Survivorship/momentum signal |
| `meta_strategy_id` | `entry_primitive` | Group results by entry family |
| `regime_filter_count` | # of active regime filters | Selectivity proxy |

## Storage scaling math

- 16 symbols × 5,000 trials per symbol × 50ms per trial = ~67 minutes per night
- Or: 1 night = 80,000 trials = ~80,000 rows in `optimization_runs`
- 7 nights = 560,000 rows. SQLite handles this easily.

DB will grow to ~200MB after a week of runs. Acceptable.

## Sampling strategy

Pure random first (uniform over each param's range). After 10k trials,
evaluate which params/blocks matter:
- Information coefficient of each param vs `score`
- Mutual information for categoricals
- Pearson correlation for continuous

Then weight subsequent samples toward winning regions (Bayesian
optimization / TPE-style). For now, plain random — gather data first.

## Walk-forward validation

After collecting a target number of trials, do an in-sample / out-of-sample
split:
- IS = 2022-01 to 2024-12 (3 years)
- OOS = 2025-01 to 2026-05 (16 months)

A "true winner" is a config whose IS-period score is in top-10% AND whose
OOS score is within 30% of its IS score. Anything that wins big in IS and
collapses OOS is overfit and rejected.

## Output: `vector_analysis_report.md`

Generated by querying the populated DB, producing:

1. Top 20 trials by OOS-stable-score
2. Per-feature PDF/violin plots of score conditional on feature value
3. Cluster analysis on the top-1000 winners (UMAP 2D scatter)
4. "Recipe cards" — translated representative cluster centroids back to
   readable strategy specs
