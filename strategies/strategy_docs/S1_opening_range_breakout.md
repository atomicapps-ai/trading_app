# S1 — Opening-Range Breakout + Retest

**Source videos:** qcFpcTAzWXQ (30-min ORB), I29peidTQxU (15-min ORB Short).
**Family:** intraday breakout + retest. **Data fit:** intraday — tested on 15m **stocks** (the videos
trade NQ futures, so regime-flag applies). **Verdict: ✅ first-pass positive; retest > chase.**

## The strategy (plain rules)
Mark the opening range (first 30 min, 09:30–10:00 ET). Wait for a 5-min candle to **close** outside
it (not just wick) → direction. **Don't chase** — enter on the **first retest** of the broken level;
tight stop the other side; let it run to the close.

## Precise definitions (as backtested)
- Opening range = high/low of 09:30–09:59 ET bars. Break = first 15m bar after 10:00 closing beyond
  the range. **Retest entry:** first pullback to the broken level. **Chase entry:** at the break close.
- Stop = level ∓ **0.20 × OR-width**. Exit = end of day. Compared retest vs chase.

## Backtest configuration
6 symbols · 15-minute bars · per-day opening-range logic · chronological IS/OOS (second-half OOS) ·
R = 0.20×OR-width. *(Run on a separate intraday script, not the daily harness — quick-pass scope.)*

## Results
| Entry | n | win% | expectancy | OOS expectancy |
|---|---|---|---|---|
| **Retest** | 5,384 | 26.6% | +0.167R | **+0.102R** |
| Chase | 6,472 | 32.8% | +0.047R | +0.004R |

## Reading the result
- The video's core claim holds: **entering on the retest beats chasing the breakout** (OOS +0.102R vs
  ~0). Positive but with a brutal **~27% win rate** (trend-day profile; winners run to the close).
- This is a first-pass on only 6 stock symbols with assumed stop/exit; the videos' native instrument
  is index futures.

## Caveats / next steps
- Re-run across the full 15m universe; sweep the stop (0.1/0.2/0.3×OR) and exit; test on QQQ/NQ.
  Add VWAP/EMA confluence at the retest (H-ORB3). Treat as promising, not proven.
