# O5eC5lY7ZXY — "4-hour range" false-breakout fade scalp

Source: <https://www.youtube.com/watch?v=O5eC5lY7ZXY>

## Rules (mechanical) — 5-min scalp, both directions
- Mark the high/low of the **first 4-hour candle of the NY day** = the range.
- On the 5-min chart, wait for a candle to **close outside** the range (wicks don't count):
  close above high → short signal; close below low → long signal (fade the failed breakout).
- Wait for price to **re-enter and close back inside** the range → entry at that close.
- **Stop** = the exact extreme of the breakout move. **Target** = 2× stop distance (2R).
  Same-day only; multiple setups per day allowed.

## Backtest (strategy_suite rig, FX 10 pairs, 5m, first-NY-4H range, both directions)
| Variant | n | win% | ALL PF | OOS PF | OOS avg-R | Control PF |
|---|---|---|---|---|---|---|
| 4H-range fade, 2R | 266,146 | 9.2% | 0.02 | 0.02 | −3.6 | 0.02 |

Script: `scripts/bt_4hrange_fade.py`; JSON: `data/research/strategy_results/fourhr_range_fade_video.json`.

## Verdict: REJECT
Fails decisively. The failed-breakout fade of the first-4H range wins only **9.2%** of the time
with a 2R target — that alone is a losing proposition *before any costs* (≈ −0.72R gross
expectancy at a 9% hit rate on 2R). After re-entering the range the stop (the breakout extreme)
sits close to entry, so ordinary 5-min noise stops the trade out long before the far 2R target
prints. The random-direction control is equally dead (PF 0.02), confirming there's no
directional edge to salvage.

Caveat (documented for the run): the harness charges a fixed 10-bps round-trip cost expressed
in R, which is calibrated for equities and is *punitive* on tiny-stop intraday FX (a few-pip
stop → cost of ~2–4R per trade). That inflates the loss magnitude here (avg-R −3.6). But the
gross 9% win rate already fails the strategy on its own merits, so the verdict is unchanged —
this is not a cost artifact, it's a no-edge setup.
Status: rejected
