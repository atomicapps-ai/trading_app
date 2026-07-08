# vLbLZWi_Ypc — "Best Stochastics strategy" (Stochastic + 200-EMA reversal)

Source: <https://www.youtube.com/watch?v=vLbLZWi_Ypc>

## Rules (mechanical) — with-trend reversal
- **200-EMA** trend filter; Stochastic %K(14,3)/%D, oversold <20 / overbought >80.
- Don't buy just because it's oversold (in a strong trend it stays pinned). Instead:
  **Long** = price above 200-EMA, stochastic was oversold, then **crosses back up above 20**
  (reversal confirmed) → enter. **Short** = mirror below the 200-EMA at overbought.
- **Stop** below the nearest swing low (long) / above swing high (short). **Target = 2× stop (2R).**

## Backtest (strategy_suite rig, 955-symbol daily US-stock universe, long side, 10bps, IS/OOS, control)
Long: close>200-EMA, %K crosses back above 20 → next open; stop = 10-bar swing low; two exits:

| Variant | n | IS PF | OOS PF | OOS avg-R | OOS win% | Control PF |
|---|---|---|---|---|---|---|
| 2R target (faithful) | 27,140 | 1.18 | 1.12 | +0.071 | 41.2% | 0.89 |
| exit at overbought (>80) | 28,722 | 1.44 | 1.16 | +0.081 | 50.9% | 0.77 |

Script: `scripts/bt_stoch_200ema.py`; JSON: `data/research/strategy_results/stoch_200ema_video.json`.

## Verdict: REJECT (marginal)
There's a faint real edge — both variants stay positive out of sample (+0.07 to +0.08R) and
beat their random-direction controls (1.12 vs 0.89; 1.16 vs 0.77) — but **neither clears the 1.2
OOS-PF bar** (2R: 1.12; overbought-exit: 1.16), and both decay IS→OOS. The stochastic-exit-from-
oversold trigger with a 200-EMA filter is a legitimate with-trend reversal, but on daily stocks
it lands just short, weaker than the passes it resembles — RSI hidden-divergence + 200-EMA + stoch
(9KVvwJHvcyE, OOS 1.21) and Connors RSI pullback (W8ENIXvcGlQ, OOS 1.31). Marginal, below
threshold → not adopted.
Status: rejected
