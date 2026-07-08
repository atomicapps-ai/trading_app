# g-PLctW8aU0 — "DEMA + SuperTrend Trading Strategy" (TradingLab)

Source: <https://www.youtube.com/watch?v=g-PLctW8aU0>

## Rules (mechanical)
- **Trend filter:** price above the **200-period DEMA** (double-EMA) → longs only (below → shorts).
- **Entry:** the **SuperTrend(ATR 12, mult 3)** indicator flips to a buy signal while price is above the DEMA; enter after the signal candle closes.
- **Stop:** the SuperTrend line at entry (its lower band).
- **Exit:** SuperTrend flips to a sell signal (it acts as a trailing stop → "infinite" upside on trend legs).
- Demoed on DOGE/LTC 15-min (crypto), but the rules are instrument/timeframe-agnostic.

## Backtest (strategy_suite rig, 955-symbol daily US-stock universe, 10bps, IS/OOS, random control)
| Variant | n | IS PF | OOS PF | OOS avg-R | Control PF |
|---|---|---|---|---|---|
| **DEMA200 filter (long)** | 26,945 | 1.42 | **1.38** | **+0.165** | 0.95 |
| no filter (long) | 42,384 | 1.36 | 1.35 | +0.151 | 0.97 |

Script: `scripts/bt_supertrend.py`; JSON: `data/research/strategy_results/supertrend_video.json`.

## Verdict: PASS
The DEMA200 + SuperTrend(12,3) trend-follower clears every bar on daily US stocks: OOS profit factor **1.38** (≥1.2), avg-R **+0.165** (>0), ~27k trades (>>100), consistent IS→OOS (1.42→1.38), and it beats its random-direction control decisively (0.95, negative expectancy) — the edge is directional, not just payoff geometry. It's a SuperTrend ATR-trailing trend follower (distinct mechanism from the Donchian/126-day-high breakouts already in the suite), so it's a genuine diversifying candidate.

Note: validated *candidate* only. The live suite already carries trend/breakout members (momentum_breakout, coil_breakout) plus the newly-validated Turtle (2ElrQnn2cZE); whether to adopt DEMA+SuperTrend as a distinct sleeve is a separate human decision (check correlation vs the existing breakout book first). Recorded as a clean, strongly-validated mechanical pass.
Status: passed
