# AKkeB8RJ6jM — "Buy Pullbacks (weakness in strength)" (swing-trading educational)

Source: <https://www.youtube.com/watch?v=AKkeB8RJ6jM>

## Rules (mechanical core)
- **Market filter:** general market in an uptrend (author uses a 10/20-EMA regime).
- **Stock uptrend:** higher highs/lows + rising 50-day MA (close > SMA50).
- **Setup:** buy a 10–20% pullback to the **21-day EMA** (or 50-day MA / prior breakout level).
- **Entry:** a supported "upside reversal" day — opens weak, closes strong (close in top ~40% of range), on volume ≥ 20-day average; enter next open.
- **Stop:** just below the reversal-day low. **Exit:** let winners run; cut on a decisive close back below the moving average.
- **Soft/discretionary layers:** "conviction," institutional sponsorship, reverse-pyramid sizing.

## Backtest (strategy_suite rig, 955-symbol daily universe, 10bps, IS/OOS, random control)
21-EMA pullback + green reversal-candle + volume, stop floored at 0.5·ATR(14) to remove the tiny-risk artifact (the un-floored version in `bt_video_candidates2.py` printed nonsense avgLoss ≈ −43R):
| Variant | n | OOS PF | OOS avg-R | Control PF |
|---|---|---|---|---|
| trailing-EMA exit + SPY-bull filter | 40,355 | 0.99 | −0.01 | 0.82 |
| 3R target + SPY-bull filter | 33,716 | 1.00 | −0.00 | 0.86 |
| trailing-EMA exit, no market filter | 52,637 | 1.02 | +0.01 | 0.84 |

Script: `scripts/bt_pullback.py`; JSON: `data/research/strategy_results/pullback_video.json`.

## Verdict: REJECT — break-even, fails the bar.
The mechanized 21-EMA pullback-in-uptrend is essentially flat: OOS profit factor ~1.0 and avg-R ≈ 0 across all variants. It does edge out its random-direction control (0.82–0.86), so there is a *faint* directional signal, but net expectancy after costs is zero and OOS PF is nowhere near the 1.2 threshold. The video's actual edge lives in the discretionary parts (stock "conviction," institutional sponsorship, which pullback to trust) that don't survive mechanization. Related live strategies (`fear_dip_reversion`, `coil_breakout`) already occupy the pullback/contraction niche with real edges.
Status: rejected
