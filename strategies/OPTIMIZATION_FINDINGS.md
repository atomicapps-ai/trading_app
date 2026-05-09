# Optimization Findings — 2026-05-09 05:04 UTC

Generated from 11,840 optimizer runs over 48 eligible (strategy, symbol) pairs.

---

## 1. Per-strategy summary

Median across symbols where the strategy met n≥30 + PF>1 eligibility.

```
strategy                      #sym  med PF  med WR%   med N       sum$    best sym   best score
-----------------------------------------------------------------------------------------------
bollinger_rsi_chartart           5    3.56     93.3      36      29140         IWM        13.43
macd_sma200_chartart            11    5.58     12.8      38     346515        AAPL         2.27
pmax_explorer                   16    2.16     41.6      44     577421        NVDA         7.47
supertrend_kivanc               16    1.40     40.0     155     396042        TSLA         4.48
```

## 2. Best strategy per symbol (cross-strategy winners)

Which strategy works best for each symbol, after per-symbol param tuning.

```
symbol best strategy                   PF   WR%     N      net$  score
----------------------------------------------------------------------
AAPL   macd_sma200_chartart          5.58  16.7    30     17097   2.27
AMD    pmax_explorer                 3.29  47.2    36     84897   3.88
AMZN   pmax_explorer                 2.02  43.5    46     28913   1.71
BA     bollinger_rsi_chartart        3.56  70.5    44     20815   6.82
COST   macd_sma200_chartart          4.85  12.1    66     24409   1.96
GS     pmax_explorer                 2.66  47.6    42     30717   2.95
HD     bollinger_rsi_chartart        3.26  94.7    38      2229   7.78
INTC   pmax_explorer                 2.77  36.8    38     48437   2.38
IWM    bollinger_rsi_chartart        7.61  96.9    32      2560  13.43
META   pmax_explorer                 3.56  50.0    42     46832   4.79
MSFT   pmax_explorer                 2.29  40.0    40     25983   1.90
NVDA   pmax_explorer                 5.91  52.9    34    137994   7.47
ORCL   macd_sma200_chartart          4.68   6.2    32     13090   0.80
SPY    bollinger_rsi_chartart        3.59  91.7    36      1667   8.51
TSLA   pmax_explorer                 4.39  42.4    33     56146   5.03
XLF    bollinger_rsi_chartart        3.56  93.3    30      1870   8.11
```

## 3. Heat map (best PF & score per (strategy, symbol))

```
symbol  bollinger_rsi_char  macd_sma200_charta       pmax_explorer   supertrend_kivanc
--------------------------------------------------------------------------------------
AAPL                     —  PF5.58 S 2.27  PF1.97 S 1.69  PF1.73 S 1.31
AMD                      —  PF6.47 S 1.35  PF3.29 S 3.88  PF1.61 S 1.39
AMZN                     —                   —  PF2.02 S 1.71  PF1.41 S 0.69
BA      PF3.56 S 6.82                   —  PF1.97 S 1.60  PF1.45 S 0.98
COST                     —  PF4.85 S 1.96  PF1.49 S 0.93  PF1.46 S 0.94
GS                       —  PF4.95 S 2.27  PF2.66 S 2.95  PF1.26 S 0.60
HD      PF3.26 S 7.78  PF4.76 S 1.77  PF1.40 S 0.73  PF1.39 S 0.88
INTC                     —  PF16.15 S 1.66  PF2.77 S 2.38  PF1.27 S 0.59
IWM     PF7.61 S13.43                   —  PF1.65 S 0.99  PF1.02 S 0.04
META                     —  PF6.85 S 1.77  PF3.56 S 4.79  PF1.73 S 1.42
MSFT                     —  PF10.07 S 1.73  PF2.29 S 1.90  PF1.30 S 0.54
NVDA                     —  PF9.08 S 2.22  PF5.91 S 7.47  PF2.03 S 1.88
ORCL                     —  PF4.68 S 0.80  PF1.22 S 0.27  PF1.06 S 0.11
SPY     PF3.59 S 8.51  PF4.92 S 2.02  PF1.63 S 1.14  PF1.34 S 0.63
TSLA                     —                   —  PF4.39 S 5.03  PF3.17 S 4.48
XLF     PF3.56 S 8.11                   —  PF2.50 S 2.28  PF1.31 S 0.65
```

## 4. Primitive frequency in winners

Counting how many (strategy, symbol) winners use each indicator family. Tells us which primitives have real edge across the universe.

```
Primitive frequency in winners (PF≥1.5, N≥30):

primitive                  count
---------------------------------
atr_band                      18
atr                           18
ma                            13
macd                          11
long_ma_regime_filter         11
bollinger_bands                5
rsi                            5
atr_stop                       5
```

## 5. Param-value frequency in eligible winners

When a (strategy, symbol) pair makes it past the PF≥1.5 / N≥30 filter, which param values show up most? This tells us where the per-symbol optima cluster — highlights regime preferences across the bellwether-16.

```
Param-value frequency in eligible winners (PF≥1.5, N≥30):

### bollinger_rsi_chartart  (n_winners=5)
  bb_length              20×4  50×1
  bb_mult                1.5×4  2.0×1
  rsi_length             6×2  20×2  4×1
  stop_atr_mult          3.0×4  2.0×1

### macd_sma200_chartart  (n_winners=11)
  fast_length            8×4  12×4  21×3
  signal_length          6×5  14×4  9×2
  slow_length            26×5  34×4  21×2
  very_slow_length       100×6  200×2  150×2  300×1

### pmax_explorer  (n_winners=13)
  atr_mult               3.0×5  4.0×5  2.0×2  2.5×1
  atr_period             7×5  10×4  21×3  14×1
  ma_length              21×5  14×3  10×3  8×2
  ma_type                'SMA'×8  'EMA'×4  'WMA'×1

### supertrend_kivanc  (n_winners=5)
  atr_mult               3.0×2  2.5×2  4.0×1
  atr_period             21×3  14×1  7×1
  use_real_atr           True×5

```

---

## Reasoning storage check

All 11,840 runs in `data/optimization_results.db::optimization_runs` carry their full param set, score, and trade summary. Per-param reasoning is in `param_reasoning` (the *why* for each param value's range). Winning combos for each (strategy, symbol) are in `best_per_symbol` with a human-readable selection rationale. Wipe the DB to re-run; checkpointing means no lost work.