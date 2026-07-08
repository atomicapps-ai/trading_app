# k-X0164r66U — "The 2 swing strategies I used to make $100M" (Lance)

Source: <https://www.youtube.com/watch?v=k-X0164r66U>

## Rules (as described — conceptual, daily charts)
1. **Mean reversion — "right side of the V":** after a sharp, extended, *capitulatory* move (massive volume, accelerating rate-of-change, emotional exhaustion), buy when the trend breaks and price turns up; initial stop at the lows, then trail prior-daily-bar lows.
2. **Continuation:** major multi-month breakout in an "in-play" stock with a catalyst (earnings, hot theme like AI/semis); buy the breakout level, stop below resistance / lows of day, trail prior-daily-bar lows or the 20-day MA.

## Backtest reference (both already mechanized in the suite)
- Mean-reversion V ≈ `s6_capitulation_v`: **OOS PF 1.19, avg-R +0.05**, beats control (0.75) — *just* under the 1.2 bar. (`data/research/strategy_results/s6_capitulation_v.json`)
- Continuation breakout ≈ the live **`momentum_breakout`** (126-day-high breakout, volume + SPY>200MA, 50-SMA trail) — already deployed and validated.

## Verdict: REJECT — conceptual overview, no new spec, strategies already covered.
The video is a swing-trading philosophy talk (time-frame trade-offs, sizing, overnight risk) with two loosely-described setups. Both map to strategies the project already has: the capitulation-V reversion (`s6`, marginal at OOS PF 1.19 — just misses the bar) and the catalyst breakout (`momentum_breakout`, live). No precise new mechanical rules, and the "in-play stock / catalyst" selection is discretionary. Nothing new to adopt.
Status: rejected
