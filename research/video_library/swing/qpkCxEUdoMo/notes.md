# qpkCxEUdoMo — "Mean Reversion Strategy (4 candles)" (The Transparent Trader / Jared Goodwin)

Source: <https://www.youtube.com/watch?v=qpkCxEUdoMo>

## Rules (mechanical) — daily
- **Entry:** after **4 consecutive red daily candles** (close < open), buy at the 4th close. Mirror: 4 green candles → sell short. (Video designed for GBP/USD daily; tested here on daily US stocks, long side.)
- **Stop:** wide fail-safe (video: 500 pips ≈ ~3·ATR; mean-reversion is hurt by tight stops).
- **Exits (5 tested, all profitable):** stop-and-reverse; close back above a ~25-SMA (mean); first profitable close; time-based (N days); RSI(5) 70/30. Author trades a split of 10/20/40-day time exits.

## Backtest (strategy_suite rig, 955-symbol daily US-stock universe, 10bps, IS/OOS, random control; entry at 4th close, stop = entry−3·ATR)
| Exit | n | win% | OOS PF | OOS avg-R | Control PF |
|---|---|---|---|---|---|
| **time-20-day** | 62,960 | 52% | **1.42** | +0.144 | 0.94 |
| **close > 25-SMA (mean)** | 56,756 | 71% | **1.39** | +0.090 | 0.92 |
| first profitable close | 85,760 | 78% | 1.23 | +0.025 | 0.83 |

Script: `scripts/bt_4candles.py`; JSON: `data/research/strategy_results/c4_video.json`.

## Verdict: PASS
The "4 consecutive down days → buy" mean-reversion clears every bar comfortably on multiple independent exits: OOS profit factor **1.39–1.42** (mean/time exits), avg-R +0.09/+0.14 (>0), 57–63k trades (>>100), and every variant beats its random-direction control (0.83–0.94). OOS is even a touch stronger than in-sample, so it has held up. Remarkably it's the *simplest* trigger tested in this run (just count four red candles) yet the strongest mean-reversion result — beating RSI-2 (1.13), Fib-discount (1.16), supply/demand (1.04). The robustness across five exits (author's own finding) is a good sign the entry has a real edge.

Note: validated *candidate* only. Distinct trigger from the live `fear_dip_reversion` (ATR-stretch below the 50-SMA) — a plain consecutive-down-day counter. Correlation vs the existing mean-reversion sleeve and a wider-universe/robustness check are for a separate human decision. Nothing goes live from this run.
Status: passed
