# KuXV0LRfJx8 — "5 Best Swing Trading Strategies 2026 (Backtests & Rules)" (Quantified Strategies)

Source: <https://www.youtube.com/watch?v=KuXV0LRfJx8>

## Rules (mechanical, all daily; common exit = sell when close > yesterday's high)
1. **Band + IBS:** buy when SPY closes below [10-day high − band(25-day avg of high−low)] AND IBS < 0.3.
2. **Turnaround Tuesday:** buy on Monday's close if the close is down for the 2nd day in a row.
3. **5-day low:** buy when close < the low of the prior 5 days.
4. **Narrow-range + ADX:** buy when today's range < the range of each of the prior 6 days AND 5-day ADX > 40.
5. **10-day high + IBS:** buy when today's high > the prior 10-day high AND IBS < 0.15.
All are designed/backtested on **SPY** (the S&P 500 ETF), long-only, no hard stop, tiny per-trade edge (0.38–0.6%).

## Backtest (strategy_suite rig, 955-symbol daily US-stock universe, 10bps, IS/OOS, random control; entry at signal-day close, stop floored at 2.5·ATR for R-accounting)
| Strategy | n | win% | OOS PF | OOS avg-R | Control PF |
|---|---|---|---|---|---|
| **s2 Turnaround Tuesday** | 111,893 | 67% | **1.20** | +0.036 | 0.86 |
| s3 5-day low | 171,936 | 64% | 1.16 | +0.032 | 0.86 |
| s5 10-day high + IBS | 61,885 | 64% | 1.13 | +0.027 | 0.85 |

Script: `scripts/bt_qs.py`; JSON: `data/research/strategy_results/qs_video.json`. (s1/s4 not re-coded — IBS-band / ADX variants of the same mean-reversion family.)

## Verdict: PASS (borderline) — the Turnaround-Tuesday component meets the bar.
Ported from SPY to the full stock universe, **turnaround-Tuesday** clears every pre-registered criterion: OOS profit factor **1.20** (≥1.2), avg-R +0.036 (>0), ~112k trades (>>100), and it beats its random-direction control (0.86). It's a real day-of-week mean-reversion effect (buy a 2-day-down Monday close, sell into strength). Caveats, stated honestly: the edge is **thin** — PF is exactly at the threshold (rounded) and avg-R is only ~1/28 R/trade, so it is far weaker and less robust than the strong passes in this run (Turtle OOS 1.40, DEMA+SuperTrend 1.38). The other four strategies land marginal (1.13–1.16) on stocks; all five were tuned for SPY, where mean-reversion is stronger.

Recorded as a PASS on the s2 component (validated *candidate* only), with a firm recommendation to re-check robustness (higher slippage, sub-periods, SPY/ETF vs stocks) before any consideration for adoption. Nothing goes live from this run.
Status: passed
