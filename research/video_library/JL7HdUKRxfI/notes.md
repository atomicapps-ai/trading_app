# JL7HdUKRxfI — "Only Swing Trading Video Beginners Need" (Trade with Pat)

Source: <https://www.youtube.com/watch?v=JL7HdUKRxfI>

## Rules (mechanical core)
- **Trend:** price above the 50-EMA (uptrend → longs only).
- **Pullback:** ≥3 red candles; wait for price to retrace into the **"discount zone"** — below the 50% Fibonacci retracement of the last swing-low→swing-high.
- **Confluence:** "look left" for a prior support/demand level inside the discount zone.
- **Entry:** on a green confirmation candle close. **Stop:** below the pullback low / support. **Target:** let it run (multiple R).
- Multi-asset/forex-framed (oil, gold, Bitcoin, NASDAQ, FX pairs); timeframes 1h/4h/daily.

## Backtest (strategy_suite rig, 955-symbol daily universe, 10bps, IS/OOS, random control)
EMA50 uptrend + <50% Fib discount + green confirmation, stop floored at 0.5·ATR (the un-floored P3 version in `bt_video_candidates2.py` produced a risk artifact):
| Variant | n | OOS PF | OOS avg-R | Control PF |
|---|---|---|---|---|
| 3R target | 51,958 | 1.08 | +0.06 | 0.89 |
| trailing-EMA exit | 56,693 | 1.16 | +0.09 | 0.89 |

Script: `scripts/bt_fibdiscount.py`; JSON: `data/research/strategy_results/fibdiscount_video.json`.

## Verdict: REJECT — marginal, fails the bar.
The Fib-discount pullback is faintly positive (OOS PF 1.08–1.16, avg-R +0.06 to +0.09) and beats its coin-flip control (0.89), but it stays **below the 1.2 OOS-PF threshold**. This matches the earlier independent finding for the same setup (video bQP6vLB7ius: +0.06R, PF 1.10). The "look-left support" confluence is discretionary and the framing is multi-asset/forex. Not adopted.
Status: rejected
