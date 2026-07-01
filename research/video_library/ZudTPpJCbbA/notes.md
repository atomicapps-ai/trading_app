# ZudTPpJCbbA — "Avoid False Breakouts" (TradingLab)

Source: <https://www.youtube.com/watch?v=ZudTPpJCbbA> · ~8 min.

## Rules (mechanical)
- entry: Draw support/resistance on a hand-identified consolidation pattern (wedge/flag/rectangle/triangle/pennant). On a resistance break, require a "momentum candle" = one large-bodied candle whose majority body closes beyond the level, OR three consecutive same-direction candles. Enter at the close of that confirmation.
- exit/stop/target: Stop just below the broken resistance. 2-step TP: sell half at 1.5R, raise stop to the old TP, trail the remainder with the Chandelier Exit (ATR multiplier = 2) and exit when it flips color.
- filters/params: Chandelier stop ATR×2; 1.5 R:R first leg.

## Verdict: ❌ REJECT — discretion (hand-drawn levels/patterns)
The trigger depends on a human drawing the consolidation box and naming the pattern; "majority of body beyond the level" and pattern recognition are not objective. The exit half (Chandelier ATR trail) is mechanical and daily-compatible, but with no programmatic breakout level there's no testable entry. The underlying idea (volume/body-confirmed level breakout) is already covered by our deployed Momentum Breakout (126-day-high + vol≥1.5x + ADX≥20).
Status: rejected, not deployed
