# 2ElrQnn2cZE — "Richard Dennis / Turtle Traders strategy" (trading-history channel)

Source: <https://www.youtube.com/watch?v=2ElrQnn2cZE>

## Rules (mechanical)
- **Instrument/timeframe:** any liquid market; demo on 1h but the author explicitly extends it to daily/weekly (uses 55-period on higher timeframes). Tested here on **daily US stocks**.
- **Trend filter:** 200-period SMA. Price above 200-SMA → take **long** breakouts only.
- **Entry:** close breaks the prior **N-day high** (Donchian channel breakout). N=20 (short/medium) or 55 (higher timeframe). Enter next open.
- **Stop:** entry − **2 × ATR(20)** ("2N").
- **Exit / target:** none fixed — *let profits run*; exit when close breaks the prior **M-day low** (M=10 for the 20-day system, 20 for the 55-day system). Classic asymmetric payoff (small frequent losses, occasional large trend wins).

This is the canonical **Turtle Trading / Donchian breakout** system.

## Backtest (strategy_suite rig — 955-symbol daily universe, 10 bps round-trip, IS/OOS split, random-direction control)
| Variant | n | OOS PF | OOS avg-R | IS PF | Control PF |
|---|---|---|---|---|---|
| **55/20 + 200MA trend (System 2)** | 25,767 | **1.40** | **+0.256** | 1.48 | 0.93 |
| 20/10 + 200MA trend (System 1) | 42,006 | 1.24 | +0.132 | 1.31 | 0.93 |
| 20/10 no trend filter | 50,081 | 1.26 | +0.139 | 1.27 | 0.93 |

Script: `scripts/bt_turtle.py`; raw JSON: `data/research/strategy_results/turtle_video.json`.

## Verdict: PASS
The System-2 (55-day entry / 20-day exit / 2N stop / 200-MA filter) variant clears every bar: OOS profit factor 1.40 (≥1.2), avg-R +0.26 (>0), ~25.8k trades (>>100), and it decisively beats its random-direction control (PF 0.93, negative expectancy) — the edge is directional, not just payoff geometry. Win rate is low (~31%) as expected for a trend-follower; the edge is in letting winners run (avg win ~3R). System-1 (20/10) also passes but with a thinner edge.

Note: this is a validated *candidate* only. The live suite already carries a breakout member (`momentum_breakout`, a 126-day-high variant); adopting the Turtle 55/20 as a distinct strategy is a separate human decision. Recorded here as a clean, strongly-validated mechanical pass.
Status: passed
