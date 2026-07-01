# pCmJ8wsAS_w — Bollinger Band + RSI mean reversion (TradingLab)

Source: <https://www.youtube.com/watch?v=pCmJ8wsAS_w> · ~7 min, indicator combo, daily stocks.

## Rules (mechanical)
- Bollinger Bands length 30, 2σ; RSI length 13.
- **Long**: close below lower band AND RSI < 25 → mean-revert to the middle band (SMA30).
- Short: close above upper band AND RSI > 75 (we test long-only).
- Avoid narrow/squeezed bands (sideways → falling-knife risk). Bonus: RSI bullish divergence.

## Backtest (45 daily stocks, 10bps cost, long-only, stop 2×ATR, target = mid band, hold 20)
| variant | OOS n | win% | exp | PF |
|---|---|---|---|---|
| base | 2044 | 50.9% | +0.137R | 1.30 |
| uptrend-only (close>200MA) | 520 | 51.9% | +0.159R | 1.36 |

## Verdict: ⚠️ MARGINAL — overlaps Fear-Dip Reversion
Real, modest edge (best of the web-surfaced batch), but it's the **same oversold-mean-reversion
family as the deployed Fear-Dip Reversion**, which is stronger (PF 1.68 base → 3.13 tuned). Not worth
deploying as a separate strategy. Could be revisited by adding the fear-regime filter, but it would
likely just converge toward what Fear-Dip already does. Status: keep note; not deployed.
