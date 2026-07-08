# 8gWIykJgMNY — "Highly profitable Ichimoku cloud strategy" (tested 100x on bar replay)

Source: <https://www.youtube.com/watch?v=8gWIykJgMNY>

## Rules (mechanical) — Ichimoku 9/26/52
- **Long** requires all four: (1) price closes **above** the cloud, (2) **conversion > baseline**
  (Tenkan > Kijun), (3) **future cloud green** (SpanA > SpanB), (4) **lagging span (chikou)
  above the cloud**. Enter when the setup first completes. (Short = mirror.)
- **Stop:** author picks among swing high/low, the baseline (Kijun), or the far cloud edge.
- **Exit:** no fixed take-profit — traded discretionarily on bar replay ("play it out").

## Backtest (strategy_suite rig, 955-symbol daily US-stock universe, long side, 10bps, IS/OOS, control)
All four criteria as a fresh signal → enter next open. Stop = Kijun or 10-bar swing low;
exit = ride until Tenkan<Kijun, or fixed 2R:

| Variant | n | OOS PF | OOS avg-R | Control PF | note |
|---|---|---|---|---|---|
| swing stop / Tenkan-cross exit | 58,910 | 0.42 | −0.70 | 0.36 | stable |
| swing stop / 2R | 39,001 | 0.39 | −1.06 | 0.34 | stable |
| Kijun stop / * | 54–63k | 0.02–0.33 | −20 to −36 | ~0.02 | unstable (tiny-risk Kijun stops explode R) |

Script: `scripts/bt_ichimoku.py`; JSON: `data/research/strategy_results/ichimoku_video.json`.

## Verdict: REJECT
Fails decisively. On the numerically-stable configurations (swing-low stop) the four-criteria
Ichimoku long wins only ~40% with OOS profit factor **0.39–0.42** and negative avg-R, barely
above its own random-direction control (0.34–0.36). Requiring all four confirmations
(price/cloud, Tenkan/Kijun, future-cloud colour, chikou) makes the entry chronically **late** —
it triggers after the move is extended, so continuation is a coin-flip-minus-costs. The
Kijun-stop variants are worse and numerically unstable (a baseline that sits just under the
entry gives a near-zero risk denominator and blows up the R-multiple). The "highly profitable,
100 bar-replay wins" claim relies on discretionary exits that can't be reproduced mechanically.
Does not beat control; nowhere near the 1.2 bar.
Status: rejected
