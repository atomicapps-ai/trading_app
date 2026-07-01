# s4DSY3Y_N4Y — "20/50 EMA Pullback + Outside-Bar" (mechanical swing strategy)

Source: <https://www.youtube.com/watch?v=s4DSY3Y_N4Y> · ~12 min.

## Rules (mechanical)
- entry: DAILY bars only. Trend filter (3 checks, in order): (1) 20-EMA above 50-EMA for longs (below for shorts); (2) both EMAs sloping the same direction (non-flat); (3) price on the correct side of both. Then price must pull back INTO the zone between the 20-EMA and 50-EMA. Entry trigger = an **outside bar** (current candle's high>prior high AND low<prior low, i.e. body/range engulfs the prior candle) that closes in the trend direction (bullish close for longs). Enter on the close of the outside bar.
- exit/stop/target: Stop just beyond the opposite extreme of the outside bar (below outside-bar low for longs). 3-tier exit: Tier 1 — at +1R take off 50% of position; Tier 2 — move stop on remainder to break-even; Tier 3 — trail remaining 50% under the most recent swing low (above swing high for shorts), updated only on confirmed daily closes. Setup is voided if price closes beyond the 50-EMA before the trigger.
- filters/params: 20-EMA & 50-EMA (close, daily); outside-bar engulf; swing-low/high structure for trailing. Demonstrated on gold/FX but rules are instrument-agnostic and 100% daily/mechanical.

## Backtest result: ❌ REJECT — marginal, below deploy bar
Tested (45 daily stocks, 10bps cost-in-R, long-only) the regime + outside-bar-tagging-[EMA50,EMA20]-zone entry with three exits:
| exit | OOS n | win% | exp | PF |
|---|---|---|---|---|
| 3R target | 602 | 33% | +0.09R | 1.12 |
| 2R target | 624 | 39% | −0.01R | 0.99 |
| trail<EMA20 | 646 | 27% | −0.00R | 0.99 |
Best variant (3R) is OOS PF 1.12, barely above its 0.87 coin-flip control — a real but tiny edge, well short of
the deployed book (1.5–3.1) and the deploy bar. The outside-bar trigger adds little over a plain pullback. Status: rejected, not deployed.

## Original triage verdict (superseded by backtest)
🔬 BACKTEST-CANDIDATE — mechanical 20/50-EMA pullback with an outside-bar engulfing trigger; structurally distinct from the deployed strategies.
