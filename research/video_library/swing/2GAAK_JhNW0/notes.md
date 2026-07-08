# 2GAAK_JhNW0 — "Why Fibonacci retracements work" (golden-pocket 0.5–0.618 continuation)

Source: <https://www.youtube.com/watch?v=2GAAK_JhNW0>  (claims "100 backtested trades London→NY")

## Rules — FX intraday (1-min demo), continuation into the golden pocket
- Identify an **impulse leg** (swing low→high up, or high→low down); confirm a **break of structure**.
- Draw the fib start→end of the leg; wait for a pullback into the **0.5–0.618 "golden pocket."**
- Enter in the impulse direction: either a **limit at 0.618**, or on a discretionary trigger
  ("candle patterns, continuation wicks, engulfing setups").
- Stop beyond the leg origin; target the extension (video shows the −0.5 ext).

## Backtest (strategy_suite rig, FX 10 pairs, both directions, fractal-pivot legs, 10bps, IS/OOS, control)
Mechanical golden-pocket continuation: fractal-pivot (±5) leg → limit fill at 0.618 → stop
beyond origin → target = leg extension (`ext`) or fixed 2R (`r2`):

| Variant | n | win% (OOS) | OOS PF | Control PF |
|---|---|---|---|---|
| 15m ext | 69,116 | 12.7% | 0.04 | 0.02 |
| 15m 2R  | 69,116 | 11.4% | 0.02 | 0.01 |
| 30m ext | 225,488 | 18.2% | 0.09 | 0.08 |
| 30m 2R  | 225,488 | 18.6% | 0.06 | 0.06 |

avg-R negative in every variant. Script: `scripts/bt_fib_goldenpocket.py`;
JSON: `data/research/strategy_results/fib_goldenpocket_video.json`.

## Verdict: REJECT
No edge. The mechanical golden-pocket-continuation proxy wins only 11–18% of the time and its
profit factor sits *at or below* the random-direction control (0.02–0.09 vs 0.01–0.08) — i.e.
catching a pullback into 0.5–0.618 and betting on continuation is no better than a coin flip,
and loses after costs. This also matches prior art in this run: the Fib-50 pullback kernel
(bQP6vLB7ius) was already reconfirmed marginal (+0.06R). Crucially, the video's *actual* entry
is discretionary — "candle patterns, continuation wicks, engulfing setups" — so the only
mechanizable part (the 0.618 limit) carries no demonstrable edge. The "millions of traders
watch these levels" narrative doesn't survive 11 years of out-of-sample FX data.
Status: rejected
