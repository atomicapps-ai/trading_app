# YWBLKRLnrZ0 — "Range-Detector Breakout + Volume" (The Trading Geek style)

Source: <https://www.youtube.com/watch?v=YWBLKRLnrZ0> · ~10 min.

## Rules (mechanical)
- entry: Use LuxAlgo Range Detector to flag a consolidation range (min range length ≥30
  bars, width ≈1.0, ATR length 200). Enter on the close of a candle that breaks out of the
  range when (a) the breakout candle body is much larger than the in-range candles AND
  (b) breakout-bar volume is well above the recent range volume.
- exit/stop/target: Stop below the most recent swing low inside the range (with wiggle room);
  target R:R of ~3 (can run to 7+ on strong breakouts).
- filters/params: Reject low-volume / small-body pokes above resistance (fake-outs); require
  the strong-momentum + high-volume confluence.

## Backtest (45 daily stocks, 10bps cost-in-R, long-only, OOS = 2nd half by trade time)
Spec tested: close>prior 30-day high AND ATR10<ATR50 (coil contraction) AND breakout-bar TR>1.5×median TR(30)
AND volume≥1.5×avg(30) AND close>SMA200; stop = 30-day range low; target 3R.
| window | n | win% | exp | PF |
|---|---|---|---|---|
| ALL | 315 | 52.7% | +0.35R | 1.85 |
| **OOS** | 158 | **55.1%** | **+0.42R** | **2.13** |
| random control | 315 | — | −0.07R | 0.88 |

Diversification: monthly-R correlation **0.14 vs Momentum Breakout, 0.09 vs MACD-run** — essentially uncorrelated.

## Verdict: ✅ STRONG DEPLOY-CANDIDATE — best new find of the web farm
Selective (only ~7 trades/symbol over 20y), high quality (OOS PF 2.13, win 55%, +0.42R), decisively beats its
coin-flip control (0.88), AND nearly uncorrelated with the existing book — so it adds a genuinely new, high-PF
sleeve rather than overlapping Momentum Breakout. The volatility-contraction precondition (ATR10<ATR50) is what
makes it selective and is the real edge. Recommend building it as the next paper strategy (ahead of MACD-run).
Update (this mining run): confirmed as the source of the live **`coil_breakout`** strategy — now deployed (active) in `strategy_configs/coil_breakout.yaml`, OOS PF ~2.13 / +0.42R, near-uncorrelated (0.14) with the breakout book. This is one of the run's strongest passes.
Status: passed
