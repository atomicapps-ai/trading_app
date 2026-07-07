# k_kSCjdf8D0 — "Moving average crossover, the right way" (20/50)

Source: <https://www.youtube.com/watch?v=k_kSCjdf8D0>

## Rules — 20/50 MA crossover, trend-following
- Two MAs only (20 & 50), on a **higher timeframe** (daily recommended; the video warns lower
  timeframes range and whipsaw).
- Enter when SMA20 crosses **above** SMA50 (golden cross); exit on the **death cross** (mirror
  for shorts). Frames confirm: BUY at golden cross ○, Exit at death cross ○.
- The video's *differentiator* is discretionary: only trade markets that "historically react" to
  the crossover (a hindsight market-selection filter — not mechanizable).

## Backtest (strategy_suite rig, 955-symbol daily US-stock universe, long side, 10bps, IS/OOS, control)
Golden cross → next open; exit on death cross → next open. No hard stop (trend-following); R
normalised to fixed 5% nominal risk (constant → PF/win% are the true dollar figures):

| Variant | segment | n | win% | PF | avg-R |
|---|---|---|---|---|---|
| 20/50 | in-sample | 20,660 | 44.5% | 1.74 | +0.59 |
| 20/50 | **out-sample** | 20,660 | 41.8% | **1.67** | +0.60 |
| 20/50 + >200-SMA filter | out-sample | 13,392 | 42.2% | **1.66** | +0.58 |
| (control) | out-sample | — | ~49% | 0.92 | −0.09 |

Script: `scripts/bt_ma_crossover.py`; JSON: `data/research/strategy_results/ma_crossover_video.json`.

## Verdict: PASS (by the criteria) — but heavily caveated; validate before trusting
Against the objective bar it clears everything: OOS profit factor **1.66–1.67** (≥1.2), avg-R
**+0.58** (>0), tens of thousands of trades, IS→OOS consistent (1.74→1.67), and it beats its
random-direction control (0.92). The mechanism is textbook "let winners run": a ~42% win rate
carried by large winners that ride entire trends to the death cross, with whipsaws cut quickly —
the exact payoff geometry this project keeps re-learning.

**Strong caveats — treat as a soft/uncertain pass, not established alpha:**
1. **Survivorship + long-beta.** Exiting only on the death cross means trades ride trends for
   months/years, so on a universe of 955 *currently-surviving* US stocks in a secular bull the
   result is close to long-beta trend-riding. Delisted losers aren't in the set; that inflates
   any long-only trend follower. A survivorship-free and/or market-neutral (excess-vs-SPY)
   re-test is required before this is believed.
2. **Control is a weak discriminator here.** The control flips direction; in an up-market,
   shorting golden crosses naturally loses, so beating it partly just reflects long bias.
3. **Not the video's claimed edge.** What passed is the *plain* crossover; the video's own
   differentiator (only trade markets that "historically react") is discretionary hindsight and
   was not tested — and the video itself says the naked crossover whipsaws.

Validated **candidate only** — nothing goes live from this run. Flagged for a survivorship-free /
market-neutral re-validation before any adoption; likely correlated with `momentum_breakout`.
Status: passed
