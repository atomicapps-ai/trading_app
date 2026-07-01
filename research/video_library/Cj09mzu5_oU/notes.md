# Cj09mzu5_oU — "5 reversal entries" (ICT/SMC)

Source: <https://www.youtube.com/watch?v=Cj09mzu5_oU> · ~18 min. Same family as the other two ICT
videos (shared backtest in `-4IPHZwse0M/notes.md`); this one enumerates 5 entry *timings* on the
same reversal, trading win-rate for reward as you get earlier.

## The strategy (as stated)
Rule for all five: the setup must originate at a **higher-timeframe key level** (timeframe alignment,
e.g. weekly level / 4h entry). Then, safest → earliest:
1. **Universal / W2S** — weakness then strength at the level → high-probability range → continuation
   from a key level (order block / imbalance / engulfing) inside the range.
2. **Disrespect of a key level** — enter before the break of structure, on a close through an FVG/level.
3. **Edge model** — wait for a "week" candle off the level, then a confirming candle in the setup direction.
4. **CCT (candle continuity)** — bullish level → expect consecutive bullish candles; enter the
   retrace (fib 0.618 off the candle) into the next aligned candle.
5. **Wick-rejection rectangle** — a wick failing to close beyond a level = first reversal sign; draw a
   rectangle on the wick, drop to 1m, enter on the first close back through it; stop beyond the wick.

## Frames viewed
- `frame_00145s.jpg` — schematic V-bottom with the two pivot extremes circled (the "weakness" low and
  the "strength" high that bracket the high-probability range). Confirms W2S = our pivot + close-confirm.
- `frame_00236s.jpg` — EURUSD 4h replay; illustrative, no new mechanic.

## Testable hypotheses
- **H-ICT7** Weakness-then-strength (W2S) at a level predicts continuation. ❌ (it's a CHoCH variant → H-ICT1, no directional edge)
- **H-ICT8** CCT: consecutive same-direction strong candles → continuation. ⏳ untested standalone
- **H-ICT9** Wick-rejection (failure to close beyond a level) → reversal. ⏳ overlaps our pivot "close-beyond" work (wick = non-confirmation)
- **H-ICT10** Earlier entries (2→5) raise R:R at the cost of win rate. ✅ consistent w/ our 1:2 vs 1:4 result (34%→21% win, exp rises)

## Backtest
No separate run needed — every entry here is a *timing variant* of "structural break at a level," and
H-ICT10 (the video's own thesis that earlier = higher R:R, lower win) is exactly what our CHoCH
1:2-vs-1:4 sweep shows: pushing the target out drops win rate 34%→21% while raising expectancy
+0.027R→+0.066R. So the video's **internal logic is consistent with our data**, but the underlying
trigger still has no directional edge (H-ICT1 / H-ICT7) — the gain is pure payoff geometry.
The genuinely novel, untested pieces are **CCT (H-ICT8)** and the **wick-rejection rectangle (H-ICT9)**.

## Verdict
Mostly a re-skin of break-of-structure + asymmetric management. Adopt nothing yet; queue CCT and
wick-rejection as standalone tests, since those are the only mechanics not already covered.
Heavy promotion ("Edge School") throughout — treat as marketing, weight the claims accordingly.
