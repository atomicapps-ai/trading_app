# j8Q3MIwGYOk — "Top 3 strategies" (presidential cycle + ICT liquidity + Fib)

Source: <https://www.youtube.com/watch?v=j8Q3MIwGYOk>

## Rules (as described)
1. **Presidential cycle (Druckenmiller):** buy the market 2 years before a US general election, sell in the election year. (Mechanical, positional, daily.)
2. **Liquidity sweep + BOS + FVG:** mark the daily candle open/close; on 30-min, wait for a sell-side liquidity sweep beyond the open, a break of structure that *closes* above the prior high, then enter on the retrace into the fair-value gap; TP = daily close, stop below the sweep low. (ICT, intraday.)
3. **Fib golden zone + FVG:** enter where the 0.618–0.79 Fib "golden pocket" of a swing overlaps a fair-value gap; stop beyond the zone, target the swing extreme. (Discretionary.)

## Backtest — strategy 1 (already implemented as `s8_presidential_cycle`)
Pooled robustness across ~500 stocks: mean 2-year return of **pre-election** windows = **+26.0%** (n=298) vs **all** overlapping 2-year windows = **+63.6%** (n=1,327). The "buy 2 years before the election" window **underperforms** a random 2-year hold. SPY headline is only ~11 non-independent elections since 1980 — far below the ≥100-trade bar and dominated by the general bull drift.
(Cached: `data/research/strategy_results/s8_presidential_cycle.json`.)

## Verdict: REJECT.
- **Strategy 1** fails on both counts: it can't meet the trade-count/PF/avg-R bar (a once-every-4-years macro bet, n≈11), and the pooled stock test *disconfirms* the edge — pre-election 2-yr windows returned less than the average 2-yr window. The "positive every time" framing is small-sample bull-market drift, not a distinct timing edge.
- **Strategies 2 & 3** are discretionary ICT (liquidity sweeps, break of structure, fair-value gaps, Fib golden pocket), intraday-framed (30-min) with subjective level/zone selection — out of scope and not objectively mechanical.
Status: rejected
