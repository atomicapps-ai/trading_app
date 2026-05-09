# Vector Analysis — 2026-05-09 18:12 UTC

Read from `data/optimization_results.db::random_search_trials`.
Trials in DB: **11,950** · eligible (PF>1, N≥30): **3,827** · OOS-robust archetypes: **50**

---

## 1. Information coefficient — params vs full-window score

Spearman rank correlation. |IC| > 0.05 is meaningful at this sample size.
Positive = larger value → higher score.

```
           param  spearman     n
          rsi_lo    0.0855 11950
         adx_min   -0.0761 11950
        vol_mult   -0.0569 11950
      rsi_length   -0.0435 11950
         adx_max    0.0422 11950
       bb_length   -0.0422 11950
regime_ma_length    0.0390 11950
       macd_slow    0.0353 11950
         bb_mult   -0.0213 11950
          rsi_hi    0.0212 11950
        stop_pct    0.0198 11950
  time_stop_bars    0.0183 11950
     vol_pct_max    0.0160 11950
   stop_atr_mult    0.0140 11950
     vol_pct_min   -0.0137 11950
```

## 2. IC vs OOS score (the version that actually matters)

```
           param  spearman     n
        vol_mult   -0.0554 11950
         adx_min   -0.0472 11950
      rsi_length   -0.0429 11950
regime_ma_length   -0.0418 11950
 breakout_length   -0.0390 11950
     vol_pct_max    0.0338 11950
          rsi_lo    0.0271 11950
  time_stop_bars   -0.0258 11950
   stop_atr_mult   -0.0243 11950
         adx_max    0.0234 11950
       ma_length   -0.0225 11950
        atr_mult   -0.0214 11950
       bb_length   -0.0199 11950
   tp_r_multiple   -0.0152 11950
       macd_fast   -0.0148 11950
```

## 3. Categorical config rankings (mean score per choice)

### entry_primitive
```
entry_primitive    n  mean_score  median_score
macd_zero_cross 1061       0.776         0.520
 n_day_breakout 1851       0.744         0.447
    rsi_extreme 1250       0.534         0.222
       atr_band  505       0.449         0.122
     bb_extreme  679       0.330         0.028
```

### stop_type
```
    stop_type    n  mean_score  median_score
     atr_mult 1696       0.658         0.339
    fixed_pct 1792       0.610         0.319
opposite_band 1858       0.597         0.320
```

### tp_type
```
          tp_type    n  mean_score  median_score
        time_only 1702       0.720         0.400
r_multiple_single 1787       0.589         0.307
      mean_revert 1857       0.561         0.269
```

## 4. OOS-robust archetypes

Top 50 OOS-robust trials. Distribution of choices:

### entry_primitive
  n_day_breakout           28/50  (56%)
  macd_zero_cross           8/50  (16%)
  rsi_extreme               7/50  (14%)
  atr_band                  4/50  (8%)
  bb_extreme                3/50  (6%)

### stop_type
  atr_mult                 19/50  (38%)
  opposite_band            17/50  (34%)
  fixed_pct                14/50  (28%)

### tp_type
  time_only                20/50  (40%)
  mean_revert              17/50  (34%)
  r_multiple_single        13/50  (26%)

### regime_filter_count
  0 filters      13/50
  1 filters      29/50
  2 filters       7/50
  3 filters       1/50

### uses_volume_filter
  on:  9/50
  off: 41/50

### symbol_class
  tech           30/50
  index          15/50
  consumer        4/50
  financial       1/50

## 5. Top 20 individual archetype configs

- **SPY** · `n_day_breakout` · stop=atr_mult · tp=r_multiple_single · rf=1 · vol=0 → N=82 WR=63.4% PF=2.35 OOS=5.15 IS=3.54 gap=-0.45
- **GS** · `macd_zero_cross` · stop=atr_mult · tp=r_multiple_single · rf=1 · vol=0 → N=36 WR=72.2% PF=2.98 OOS=4.39 IS=3.14 gap=-0.40
- **SPY** · `n_day_breakout` · stop=opposite_band · tp=r_multiple_single · rf=1 · vol=0 → N=62 WR=75.8% PF=2.58 OOS=4.16 IS=4.93 gap=0.16
- **SPY** · `n_day_breakout` · stop=opposite_band · tp=r_multiple_single · rf=0 · vol=0 → N=54 WR=59.3% PF=2.19 OOS=3.22 IS=2.35 gap=-0.37
- **NVDA** · `n_day_breakout` · stop=fixed_pct · tp=time_only · rf=0 · vol=0 → N=62 WR=37.1% PF=3.14 OOS=2.93 IS=3.34 gap=0.12
- **SPY** · `n_day_breakout` · stop=fixed_pct · tp=time_only · rf=1 · vol=0 → N=42 WR=54.8% PF=3.11 OOS=2.93 IS=3.97 gap=0.26
- **COST** · `rsi_extreme` · stop=opposite_band · tp=r_multiple_single · rf=1 · vol=1 → N=35 WR=60.0% PF=2.58 OOS=2.93 IS=2.19 gap=-0.34
- **SPY** · `n_day_breakout` · stop=atr_mult · tp=r_multiple_single · rf=1 · vol=0 → N=45 WR=48.9% PF=3.45 OOS=2.77 IS=4.27 gap=0.35
- **SPY** · `atr_band` · stop=opposite_band · tp=r_multiple_single · rf=0 · vol=0 → N=33 WR=54.5% PF=2.43 OOS=2.77 IS=2.34 gap=-0.18
- **AMZN** · `bb_extreme` · stop=fixed_pct · tp=time_only · rf=1 · vol=0 → N=30 WR=46.7% PF=4.09 OOS=2.77 IS=3.82 gap=0.28
- **AAPL** · `bb_extreme` · stop=atr_mult · tp=mean_revert · rf=1 · vol=0 → N=86 WR=68.6% PF=1.62 OOS=2.77 IS=2.02 gap=-0.37
- **SPY** · `bb_extreme` · stop=atr_mult · tp=time_only · rf=1 · vol=1 → N=30 WR=63.3% PF=1.98 OOS=2.77 IS=1.99 gap=-0.39
- **SPY** · `n_day_breakout` · stop=opposite_band · tp=mean_revert · rf=1 · vol=0 → N=89 WR=52.8% PF=2.22 OOS=2.77 IS=2.48 gap=-0.12
- **SPY** · `atr_band` · stop=atr_mult · tp=time_only · rf=0 · vol=0 → N=34 WR=35.3% PF=3.14 OOS=2.77 IS=2.04 gap=-0.36
- **COST** · `rsi_extreme` · stop=opposite_band · tp=time_only · rf=1 · vol=0 → N=34 WR=47.1% PF=3.21 OOS=2.77 IS=3.10 gap=0.10
- **HD** · `atr_band` · stop=atr_mult · tp=mean_revert · rf=0 · vol=0 → N=33 WR=63.6% PF=2.66 OOS=2.77 IS=3.94 gap=0.30
- **SPY** · `rsi_extreme` · stop=opposite_band · tp=time_only · rf=0 · vol=0 → N=40 WR=55.0% PF=2.56 OOS=2.68 IS=2.80 gap=0.05
- **NVDA** · `macd_zero_cross` · stop=fixed_pct · tp=mean_revert · rf=1 · vol=0 → N=77 WR=50.6% PF=2.10 OOS=2.68 IS=2.02 gap=-0.32
- **AMD** · `n_day_breakout` · stop=opposite_band · tp=r_multiple_single · rf=1 · vol=1 → N=98 WR=41.8% PF=2.27 OOS=2.57 IS=2.37 gap=-0.08
- **AAPL** · `macd_zero_cross` · stop=atr_mult · tp=mean_revert · rf=1 · vol=0 → N=57 WR=56.1% PF=2.13 OOS=2.35 IS=3.02 gap=0.22