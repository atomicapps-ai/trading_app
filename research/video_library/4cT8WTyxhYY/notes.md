# 4cT8WTyxhYY — "Liquidity Grab reversal" (TradingLab / "Mr Double Your Money")

Source: <https://www.youtube.com/watch?v=4cT8WTyxhYY>

## Rules (kernel, stripped of proprietary indicator)
- **Instrument/timeframe:** pitched for "stocks, forex, crypto, all timeframes."
- **Entry:** a "liquidity grab" = price pokes through a prior support/resistance then closes back (a failed breakout). Long after a failed breakdown (sweep of lows, close back above); short after a failed breakout. Enter at/after the grab candle.
- **Stop:** just beyond the grab extreme. **Target:** the recent opposite swing (recent high for longs).
- **Add-ons (discretionary):** proprietary "show reversals" paid indicator does the marking; "peaks <10 candles apart" filter; momentum divergence confluence; higher-timeframe S/R alignment. Also promotes a forex broker deposit-match.

## Backtest (strategy_suite rig, 200-symbol daily universe, 10 bps, IS/OOS, random control)
Mechanized kernel: sweep of prior 20-day low/high with close back inside → enter next open; stop = grab extreme floored at 0.5·ATR(14); target = prior 20-day opposite channel.
| Variant | n | OOS PF | OOS avg-R | Control PF |
|---|---|---|---|---|
| long (failed breakdown) | 19,013 | 1.13 | +0.11 | 0.87 |
| short (failed breakout) | 27,628 | 0.78 | −0.21 | 0.86 |
| both | 39,991 | 0.90 | −0.09 | 0.86 |

(First naive pass had a risk-definition artifact — next-open entry sat on the stop, so R exploded; fixed with a 0.5·ATR stop floor. Numbers above are the clean read.)
Script: `scripts/bt_liqgrab.py`; JSON: `data/research/strategy_results/liqgrab_video.json`.

## Verdict: REJECT — fails the pass bar.
The long-only false-breakdown reversal does show a *mild* directional edge (OOS PF 1.13, avg-R +0.11, beats its coin-flip control at 0.87), but it is **below the 1.2 OOS-PF threshold**. The short side is outright negative (PF 0.78) and the combined system loses (0.90). As pitched it's also discretionary, dependent on a paid indicator, and forex/crypto-framed. Not adopted; the long-side kernel is only marginal.
Status: rejected
