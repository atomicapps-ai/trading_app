# FqxEKDxemtI — "Extreme Fade" (3-standard-deviation Bollinger reversal)

Source: <https://www.youtube.com/watch?v=FqxEKDxemtI>  (author says he's taught it 10+ years)

## Rules (mechanical) — mean reversion from a 3SD stretch, demoed on 15-min FX
- Plot Bollinger Bands on the 20-SMA at **both 2SD and 3SD**.
- **Long:** a bar closes **below the 3SD lower band** (extreme, "rubber band stretched 3σ").
  Don't buy yet — wait for a bar to close **back above the 2SD lower band** (confirmation the
  snap-back has begun) → enter.
- **Stop:** ~20 pips below the swing low (emergency), then trail.
- **Target:** the **basis (20-SMA)**, or the opposite band; ~modest R:R.
- **Short:** mirror (close above 3SD upper → close back inside 2SD upper).

## Backtest (strategy_suite rig, 10bps, IS/OOS, random control)
Arm on close beyond 3SD → enter next open on close back inside 2SD; stop below 5-bar swing:

| Variant | universe | n | IS PF | OOS PF | OOS avg-R | Control PF |
|---|---|---|---|---|---|---|
| long, target=basis | 955 daily stocks | 9,805 | 1.34 | **1.22** | +0.137 | 0.78 |
| long, target=opp band | 955 daily stocks | 9,736 | 1.70 | **1.40** | +0.276 | 0.82 |
| both dirs, target=basis | FX 15m | 5,820 | — | 0.03 | −2.6 | 0.02 |
| both dirs, target=basis | FX 30m | 20,097 | — | 0.07 | −1.9 | 0.06 |

Script: `scripts/bt_bb3sd_fade.py`; JSON: `data/research/strategy_results/bb3sd_fade_video.json`.

## Verdict: PASS (on daily equities)
On the daily US-stock universe the 3SD extreme-fade clears every bar and does so robustly: OOS
profit factor **1.22** (target the mean) to **1.40** (target the opposite band), avg-R +0.14 to
+0.28, ~9.8k trades, and it beats its random-direction control decisively (0.78–0.82). It holds
out of sample (IS 1.34→OOS 1.22; IS 1.70→OOS 1.40 — mild decay, still well over the bar). The
3SD trigger is more selective than the already-passed BB(2SD)+RSI mean-rev (pCmJ8wsAS_w) and a
distinct trigger from the live `fear_dip_reversion` (≥3·ATR below the 50-SMA), yet lands in the
same validated mean-reversion family — buy capitulation, target the mean.

Notable: on **FX intraday** — the video's own demo instrument — it *fails* hard (OOS PF 0.03–0.07),
exactly the failure mode the author warns about (in strong FX trends price "hugs" the band for
long stretches, so fading the extreme gets run over). The edge is an equities phenomenon here,
not an FX one. Validated **candidate only** — nothing goes live from this run; adoption and its
correlation vs the existing mean-reversion strategies is a separate human decision.
Status: passed
