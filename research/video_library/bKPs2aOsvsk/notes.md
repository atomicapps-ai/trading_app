# bKPs2aOsvsk — "Williams Fractals + moving averages" scalp

Source: <https://www.youtube.com/watch?v=bKPs2aOsvsk>

## Rules (mechanical) — trend pullback with a fractal trigger
- Indicators: Williams Fractals (period 2) + SMAs **20 / 50 / 100**.
- **Long only if stacked:** SMA20 > SMA50 > SMA100 (not crossing).
- **Entry:** price pulls back **under the 20-MA** (or under the 50-MA), then a **Williams fractal
  low** (green arrow) prints → enter.
- **Stop:** below the 50-MA (if pullback reached the 20) or below the 100-MA (if it reached the
  50). If price is below the 100-MA → no trade.
- **Target:** 1.5 × risk (1.5R). (Short = mirror.)

## Backtest (strategy_suite rig, 955-symbol daily US-stock universe, long side, 10bps, IS/OOS, control)
| Variant | n | IS PF | OOS PF | OOS avg-R | OOS win% | Control PF |
|---|---|---|---|---|---|---|
| 1.5R (faithful) | 25,752 | 1.18 | 1.08 | +0.042 | 48.2% | 0.90 |
| 2.0R | 24,740 | 1.22 | 1.11 | +0.058 | 45.4% | 0.89 |

Script: `scripts/bt_fractal_ma.py`; JSON: `data/research/strategy_results/fractal_ma_video.json`.

## Verdict: REJECT (marginal)
A faint edge that doesn't clear the bar. Both variants stay positive out of sample (+0.04 to
+0.06R) and beat their random-direction controls (1.08–1.11 vs ~0.90), but **OOS profit factor is
only 1.08 (1.5R) / 1.11 (2R)** — under the 1.2 threshold — and both decay IS→OOS. The stacked-MA +
pullback + fractal-low entry is a reasonable with-trend pullback, but the Williams-fractal trigger
adds little over a plain pullback and lands short of the passing trend/mean-reversion candidates
(Connors 1.31, hidden-divergence 1.21). Marginal → not adopted.
Status: rejected
