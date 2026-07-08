# 7NM7bR2mL7U — TradePro "triple-EMA + Stochastic-RSI" scalp

Source: <https://www.youtube.com/watch?v=7NM7bR2mL7U>  ("won all 15 trades, tested 100x")

## Rules (mechanical) — FX intraday, both directions
- **Indicators:** EMA 8, EMA 14, EMA 50; Stochastic-RSI (3,3,14,14 TV default); ATR(14).
- **Long:** EMAs stacked up (8 > 14 > 50), a Stoch-RSI **cross up**, and the trigger candle
  **closes above all three EMAs** → enter next open.
- **Short:** EMAs stacked down (8 < 14 < 50), Stoch-RSI **cross down**, candle closes below all 3.
- **Target = 2 × ATR14. Stop = 3 × ATR14** (wider stop than target → "high win rate scalp").

## Backtest (strategy_suite rig, FX 10 pairs = 9 majors + XAUUSD, both directions, 10bps, IS/OOS, control)
| Variant | n | win% (OOS) | OOS PF | OOS avg-R | Control PF |
|---|---|---|---|---|---|
| 15m | 25,278 | 13.1% | **0.03** | −1.03 | 0.04 |
| 30m | 76,217 | 31.4% | **0.08** | −0.66 | 0.16 |

Script: `scripts/bt_ema_stochrsi.py`; JSON: `data/research/strategy_results/ema_stochrsi_video.json`.

## Verdict: REJECT
Decisively negative. On 11 years of FX intraday the win rate is 13–31%, nowhere near the
>60% required to profit from a 2:3 reward-to-risk geometry, so OOS PF collapses to 0.03–0.08
and avg-R is deeply negative. The random-direction control is *also* terrible (0.04 / 0.16),
which tells the real story: the specified 2·ATR-target / 3·ATR-stop payoff shape is a
structural loser after costs on this data, and the EMA+StochRSI entry does nothing to rescue
it (15m is actually *below* its own coin-flip control). The video's "won all 15 in a row"
is cherry-picked, not a repeatable edge. Does not beat control; fails every bar.
Status: rejected
