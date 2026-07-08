# gvzCDqjccLs — "Improved 2-Period RSI Strategy" (The Transparent Trader / Connors)

Source: <https://www.youtube.com/watch?v=gvzCDqjccLs>

## Rules (mechanical) — daily
- **Filter:** close > 200-SMA (long-only uptrend).
- **Entry:** 2-period RSI crosses **below 10** (Connors also uses 5) → buy next open.
- **Exit:** baseline = RSI(2) > 70; modification = **first profitable close** (optionally after an N-day delay, the video's "12-day delay" tripled net profit on SPX).
- **Stop:** Connors uses none; the video uses a fixed 200-pt stop on the S&P 500 index (SPX CFD).
- Demonstrated on the **S&P 500 index**, not individual stocks.

## Backtest (strategy_suite rig, 955-symbol daily US-stock universe, 10bps, IS/OOS, random control)
RSI(2)<10 above SMA200, stop floored at 2.5·ATR(14) for R-accounting (Connors' no-stop can't yield R-multiples):
| Exit variant | n | win% | OOS PF | OOS avg-R | Control PF |
|---|---|---|---|---|---|
| RSI(2) > 70 | 68,567 | 65% | 1.13 | +0.03 | 0.82 |
| first profitable close | 75,880 | 74% | 0.95 | −0.01 | 0.80 |
| first profitable close, 3-day delay | 67,608 | 70% | 1.13 | +0.03 | 0.86 |

Script: `scripts/bt_rsi2.py`; JSON: `data/research/strategy_results/rsi2_video.json`.

## Verdict: REJECT — marginal, fails the bar.
There is a genuine mean-reversion edge (high win rate 65–74%, and every variant beats its random-direction control at 0.80–0.86), but the best OOS profit factor is **1.13** — below the 1.2 threshold — because the tail losses (2.5·ATR stop) offset the many small wins. The naive first-profitable-close (no delay) actually loses. This matches RSI-2's well-known behavior: it performs best on indices/ETFs (the video tests SPX itself) and has degraded on individual stocks. The suite already carries daily mean-reversion (`fear_dip_reversion`, `s5_mean_reversion`). Not adopted.
Status: rejected
