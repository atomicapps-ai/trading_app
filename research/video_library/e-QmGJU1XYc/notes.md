# e-QmGJU1XYc — "3-step supply & demand formula" (price-action)

Source: <https://www.youtube.com/watch?v=e-QmGJU1XYc>

## Rules (mechanical)
1. **Market structure / trend:** validated swing highs/lows — a "low" only counts once price has broken the prior swing high. Trade only with the trend (longs in uptrend, shorts in downtrend).
2. **Supply/demand zones:** mark the consolidation candle just before a sharp impulse move (demand in uptrend, supply in downtrend). Enter on a retest of the zone; stop just beyond the zone; target the recent swing high/low.
3. **R:R filter:** take the trade only if risk-to-reward ≥ **2.5:1**.

Maps directly to the harness's `s4_supply_demand` (trend-filtered demand-zone retest) and its `rr25` variant (the 2.5:1 filter).

## Backtest (strategy_suite rig, ~500-symbol daily universe, 10bps, IS/OOS, random control)
| Variant | n | OOS PF | OOS avg-R | Control PF |
|---|---|---|---|---|
| demand-zone retest, no R:R filter | 15,395 | 0.91 | −0.05 | 0.80 |
| + R:R ≥ 2.5 filter (the video's rule) | 4,338 | 1.04 | +0.03 | 0.88 |

Cached: `data/research/strategy_results/s4_supply_demand{,_rr25}.json`.

## Verdict: REJECT — marginal, fails the bar.
The base demand-zone retest actually loses money (OOS PF 0.91). The video's own key improvement — only taking ≥2.5:1 setups — lifts it to OOS PF 1.04 / avg-R +0.03, which beats a coin-flip control (0.88) but is nowhere near the 1.2 threshold. The video only shows cherry-picked winners; systematically it's break-even at best. Zone identification is also discretionary. Not adopted.
Status: rejected
