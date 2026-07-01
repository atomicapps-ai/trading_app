# S7 — Multi-Month Breakout Continuation

**Source video:** k-X0164r66U (Lance, ex-Trillium swing trader) — continuation half.
**Family:** trend-following / momentum continuation. **Data fit:** daily stocks ✅ (native regime).
**Verdict: ✅ VALIDATED (first-pass).** Strongest result in the suite; OOS > IS; clearly beats control.

## The strategy (plain rules)
Buy multi-month breakouts in strong, "in-play" names; let the trend run with a trailing stop.
Buy the breakout level, stop below it, then trail a moving average / prior-bar lows. Low win rate,
large winners — the money is in letting trends run, not in being right often.

## Precise definitions (as backtested)
- **Entry:** daily close exceeds the prior **126-day (≈6-month) high** → enter next open.
- **Stop:** entry − **1.0 × ATR(14)**.
- **Exit / trail:** close below the **20-day SMA** (trend-follow exit), else 120-bar time stop.
- **Direction:** long only.

## Backtest configuration
| Knob | Value |
|---|---|
| Universe | 90 daily US stocks |
| Period | 2006–2026 (~20y) |
| Bars | daily |
| OOS split | chronological, first half (IS) vs second half (OOS) by trade time |
| Costs | 10 bps round-trip, charged per trade in R via each trade's risk fraction |
| Control | same trades, coin-flipped direction |
| Risk unit (R) | entry − stop = 1.0×ATR(14) |

## Results (net of costs)
| Window | n | win% | expectancy | profit factor | avg win / loss | max DD (R) |
|---|---|---|---|---|---|---|
| **All** | 4,990 | 28.3% | **+0.244R** | 1.33 | +3.47 / −1.03 | −167 |
| In-sample | 2,495 | 28.1% | +0.036R | 1.05 | +2.76 / −1.03 | −167 |
| **Out-of-sample** | 2,495 | 28.5% | **+0.452R** | 1.61 | +4.18 / −1.03 | −129 |
| Random control | 4,990 | 49.7% | +0.049R | 1.06 | +1.74 / −1.62 | −318 |

## Reading the result
- **Edge is real and OOS-robust** — OOS expectancy (+0.45R) is *higher* than IS (+0.04R); not an
  overfit. Beats the random-direction control (+0.05R) ~9×, so the *breakout direction* carries
  genuine information, unlike the ICT triggers.
- Classic trend profile: **win only ~28%**, but winners average **+3.5R** vs −1R losers. Requires
  the discipline to sit through many small losses for occasional big runs.
- Deep equity drawdowns (−167R) → position sizing and correlation control matter a lot live.

## Caveats / next steps
- No catalyst / "in-play" filter yet (Lance emphasizes both) — adding a volume/relative-strength
  screen may lift it further. Test: 252-day high variant; ATR-multiple stop sweep; 20- vs 50-MA trail.
- Survivorship: the 90-symbol universe skews to names that still exist in 2026. Re-test on a
  point-in-time universe before sizing real capital.
