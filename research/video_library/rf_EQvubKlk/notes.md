# rf_EQvubKlk — "MACD + 200MA Strategy (~86% WR)" (unknown channel)

Source: <https://www.youtube.com/watch?v=rf_EQvubKlk> · ~7 min.

## Rules (mechanical)
- entry (LONG): MACD line crosses ABOVE signal line while the crossover is BELOW the zero line, AND price is above the 200-day SMA. (SHORT: MACD crosses below signal ABOVE zero line, AND price below 200-day SMA.)
- exit/stop/target: stop just below the 200-day MA (200MA acts as the "wall"); profit target at 1.5R (1.5× the stop distance).
- filters/params: MACD (12/26/9 standard), 200-day SMA trend filter. Optional discretionary add-on: only take entries at a prior support/resistance bounce (this layer is discretionary — drop it for the mechanical version).

## Backtest (45 daily stocks, 10bps cost-in-R, long-only, OOS = 2nd half by trade time)
| variant | OOS n | win% | exp | PF | random-control PF |
|---|---|---|---|---|---|
| stop below 200-SMA, 1.5R target | 708 | 49.7% | +0.04R | 1.08 | 0.80 |
| ATR stop (entry−1.5×ATR), 1.5R target | 857 | 47.8% | +0.13R | 1.24 | 0.91 |

## Re-test — exit style matters (the 1.5R cap was the problem, not the entry)
| exit style | OOS n | win% | exp | PF |
|---|---|---|---|---|
| fixed 1.5R | 852 | 47.5% | +0.13R | 1.23 |
| fixed 3R | 800 | 34.6% | +0.30R | 1.43 |
| **exit on MACD cross-down (run)** | 931 | 36.9% | **+0.27R** | **1.52** |
| trail 20-MA | 931 | 28.1% | +0.15R | 1.37 |

Diversification check (monthly-R correlation, 35–45 stocks): **MACD-run vs deployed Momentum
Breakout = 0.26** (low); vs Fear-Dip = 0.30; vs Turtle = 0.44.

## Verdict: ✅ DEPLOY-CANDIDATE (as a diversifier) — the "86% WR" headline is still false
The headline win rate is fiction (~37–48% actual, never 86% — capping wins at 1.5R is the only way to *get*
~48%, and that version barely profits). But once you **let winners run** (exit on MACD cross-down), it's a
real OOS edge (PF 1.52, beats its 0.81 control) that is **only 0.26 correlated with the breakout we already
run** — so it fires at different times and adds genuine diversification, unlike the Turtle. Recommend deploying
the run-exit version as a 3rd paper sleeve (MACD(12,26,9) cross-up below zero + close>SMA200, stop entry−1.5×ATR14,
exit on MACD<signal). Status: recommended for paper deployment (run-exit variant).
