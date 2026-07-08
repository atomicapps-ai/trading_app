# pCmJ8wsAS_w — "Bollinger Bands + RSI strategy" (mean reversion)

Source: <https://www.youtube.com/watch?v=pCmJ8wsAS_w>

## Rules (mechanical) — daily (demoed on AAPL)
- **Indicators:** Bollinger Bands length **30**, 2 SD; RSI length **13**.
- **Long entry:** close below the lower band **AND** RSI < 25 → buy.
- **Short entry:** close above the upper band AND RSI > 75 (mirror).
- **Exit:** reversion to the mean (the middle band / 30-SMA).
- **Crucial tip:** do NOT trade when the bands are narrow (a squeeze / sideways market) — those break out with momentum ("don't catch a falling knife"). Optional: RSI bullish divergence as extra confirmation.

## Backtest (strategy_suite rig, 955-symbol daily US-stock universe, 10bps, IS/OOS, random control)
Long: close<lowerBB(30,2) & RSI(13)<25 → next open; target = 30-SMA (mean); stop = entry−2·ATR(14):
| Variant | n | win% | OOS PF | OOS avg-R | Control PF |
|---|---|---|---|---|---|
| BB+RSI | 11,822 | 48% | 1.25 | +0.119 | 0.94 |
| BB+RSI, skip squeezes | 11,613 | 48% | **1.28** | **+0.129** | 0.95 |

Script: `scripts/bt_bbrsi.py`; JSON: `data/research/strategy_results/bbrsi_video.json`.

## Verdict: PASS
The BB(30,2)+RSI(13) mean-reversion clears every bar: OOS profit factor **1.25** (base) and **1.28** with the video's own squeeze-avoidance filter, avg-R +0.12/+0.13 (>0), ~11.8k trades (>>100), and it beats its random-direction control (0.94–0.95). Notably it's the **first mean-reversion variant in this run to clear 1.2** — the tight double filter (band extreme AND RSI<25) is more selective/higher-quality than plain RSI-2 (1.13), single-MA pullbacks (~1.0) or supply/demand (1.04). The squeeze-avoidance tip is real signal (1.25→1.28), not noise.

Note: validated *candidate* only. Distinct trigger from the live `fear_dip_reversion` (≥3×ATR below the 50-SMA) — more frequent, band-based. Whether to adopt (and correlation vs fear_dip_reversion) is a separate human decision. Nothing goes live from this run.
Status: passed
