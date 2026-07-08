# 2G78zkuQSc0 — "Heikin-Ashi + Stochastics reversal strategy"

Source: <https://www.youtube.com/watch?v=2G78zkuQSc0>

## Rules (mechanical) — reversal entry, demoed intraday (author says "works great on 1-min")
- **Candles:** Heikin-Ashi (HA), shown alongside the real candles.
- **Trend read:** uptrend = HA green, large bodies, no lower wicks; downtrend = HA red,
  large bodies, no upper wicks.
- **Reversal trigger (long):** after a downtrend, a HA **doji** (small body, wicks both
  sides) appears, then wait for **two** strong HA candles in the new direction — green,
  large body, wick **only on top** (no lower wick) — enter on the 2nd.
- **Stochastic filter:** only take the long when Stochastic is **crossing below the lower
  band (oversold) with *weak* downward momentum** (skip strong-momentum oversold).
- **Exit:** none specified ("enter the trade → profit"). No stop / target / time rule.

## Backtest (strategy_suite rig, 955-symbol daily US-stock universe, 10bps, IS/OOS, random control)
HA long: prior 3-of-4 HA bearish → HA doji (body≤0.35·range, both wicks) → 2 strong-bull
HA (body≥0.5·range, lower-wick≤0.1·range) with Stoch %K(14,3)≤25 in the window → enter next
open. Stop = entry − 1·ATR14 (video gives no exit). Two exit variants tested:

| Variant | n | win% | OOS PF | OOS avg-R | Control PF |
|---|---|---|---|---|---|
| base: +2R target / time stop | 27,664 | 37% | 0.99 | −0.008 | 0.88 |
| haflip: ride until 2 bearish HA | 27,719 | 33% | **1.06** | **+0.033** | 0.87 |

Script: `scripts/bt_heikin_reversal.py`; JSON: `data/research/strategy_results/heikin_reversal_video.json`.

## Verdict: REJECT
The HA-doji + 2-candle reversal has a *faint* directional edge — the ride-the-HA-flip
variant clears its random-direction control (OOS PF 1.06 vs 0.87) and stays positive out of
sample (+0.033R) across ~28k trades — but it falls well short of the 1.2 OOS-PF bar, and the
target-based variant is a coin flip (OOS PF 0.99, −0.008R). The video specifies no exit at
all, so the only usable edge is the entry, and that entry alone doesn't generalize to daily
stocks above threshold. Consistent with the run's other pure-reversal kernels (marginal,
~1.0–1.1). Not adopted.
Status: rejected
