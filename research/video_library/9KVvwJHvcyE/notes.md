# 9KVvwJHvcyE — "Simple high win-rate RSI (hidden) divergence strategy"

Source: <https://www.youtube.com/watch?v=9KVvwJHvcyE>

## Rules (mechanical) — trend continuation
- **Indicators:** RSI(14), 200-EMA (trend filter), Stochastic (confirmation).
- Use RSI for **hidden divergence** (a continuation signal), not overbought/oversold.
- **Bullish hidden divergence (long):** price makes a **higher low** while RSI makes a
  **lower low**, with price **above the 200-EMA** (uptrend). Stochastic confirms (rising /
  not overbought). Enter after the higher-low confirms; ride the continuation.
- (Bearish mirror for shorts.)

## Backtest (strategy_suite rig, 955-symbol daily US-stock universe, long side, 10bps, IS/OOS, control)
Fractal-pivot (±3) lows; higher-low + RSI lower-low + close>EMA200; enter next open; stop below
the swing low. Exits: fixed 2R vs trailing-swing ("ride the trend"); ±stochastic filter (%K<45):

| Variant | n | IS PF | OOS PF | OOS avg-R | Control PF |
|---|---|---|---|---|---|
| 2R | 38,335 | 1.03 | 1.00 | −0.001 | 0.85 |
| 2R + stoch | 14,770 | 1.07 | 1.06 | +0.042 | 0.89 |
| trail | 38,335 | 1.03 | 1.08 | +0.023 | 0.67 |
| **trail + stoch (full spec)** | 14,770 | **1.10** | **1.21** | **+0.059** | 0.73 |

Script: `scripts/bt_hidden_divergence.py`; JSON: `data/research/strategy_results/hidden_divergence_video.json`.

## Verdict: PASS (borderline)
Implemented faithfully — RSI hidden divergence **plus the video's 200-EMA trend filter, its
stochastic confirmation, and a trend-riding exit** — the strategy clears every bar: OOS profit
factor **1.21** (≥1.2), avg-R **+0.059** (>0), ~14.8k trades (>>100), and it beats its
random-direction control decisively (1.21 vs 0.73). It holds out of sample (IS 1.10 → OOS 1.21,
i.e. OOS ≥ IS, not an in-sample artifact) and both halves are positive.

Caveats: this is genuinely **borderline** — it clears only in the full-spec form; drop the
stochastic filter or the trend-ride exit and it slips to ~1.0–1.08 (the plain 2R version is a
coin flip at 1.00). The edge is modest (all-sample PF 1.16). Comparable to the earlier
borderline pass KuXV0LRfJx8 (OOS 1.20). Validated **candidate only** — nothing goes live from
this run; whether to adopt it, and its correlation vs the live `macd_run` / `momentum_breakout`
trend-continuation strategies, is a separate human decision.
Status: passed
