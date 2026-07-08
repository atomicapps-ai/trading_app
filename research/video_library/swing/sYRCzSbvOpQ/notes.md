# sYRCzSbvOpQ — "Backtested 21 Years in 6 Seconds with ChatGPT" (Trading Heroes)

Source: <https://www.youtube.com/watch?v=sYRCzSbvOpQ>

## Content
A tutorial on using ChatGPT to backtest strategies from a MetaTrader CSV. The demo strategy (made up on the fly) on EUR/USD daily: buy when close < the 8-SMA while the 8-SMA > 25-SMA; exit when close closes back above the 8-SMA (mirror for shorts). No stop initially (68% win but 67% max drawdown on EUR/USD).

## Backtest (strategy_suite rig, 955-symbol daily US-stock universe, 10bps, IS/OOS, random control; stop = entry−2.5·ATR)
| | n | win% | OOS PF | OOS avg-R | Control PF |
|---|---|---|---|---|---|
| 8/25-SMA fast pullback | 199,657 | 66% | 0.99 | −0.002 | 0.83 |

Script: `scripts/bt_sma825.py`; JSON: `data/research/strategy_results/sma825_video.json`.

## Verdict: REJECT — tutorial + break-even kernel.
Primarily a how-to-backtest-with-ChatGPT tutorial; the strategy is an on-the-fly EUR/USD demo. Tested faithfully on daily US stocks, the 8/25-SMA fast pullback is **break-even** (OOS PF 0.99, avg-R ≈ 0) — it beats a coin-flip control (0.83), so there's a faint mean-reversion tilt, but it's far too frequent/unselective (~200k trades) to net an edge after costs. Not adopted.
Status: rejected
