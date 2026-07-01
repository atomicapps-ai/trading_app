# S5 — Price-Action Primitives (mean reversion to the 50-MA)

**Source video:** 0L6Rcgp6j7Y ("4 price action secrets"). **Family:** mean reversion.
**Data fit:** daily stocks ✅. **Verdict: ✅ VALIDATED (first-pass)** for the 50-MA reversion primitive.

## The strategy (plain rules)
The video offers four primitives: (1) big-body no-wick candle as an S/R level, (2) **mean reversion
to the 50-MA**, (3) momentum continuation, (4) fib-pullback depth. The author's honest caveat:
"any of these by themselves won't have a high win rate." We backtested the cleanest and most
mechanical one first — **#2, mean reversion to the 50-day moving average.**

## Precise definitions (as backtested — H-PA2)
- **Signal:** daily close ≤ **SMA50 − 2.5 × ATR(14)** (stretched well below the mean).
- **Entry:** next open. **Target:** the SMA50 (the mean). **Stop:** entry − 1.0×ATR(14).
- **Max hold:** 30 bars. **Direction:** long only.

## Backtest configuration
Universe 90 daily stocks · 2006–2026 · daily bars · chronological IS/OOS split · 10 bps round-trip
cost in R · random-direction control · R = 1.0×ATR(14).

## Results (net of costs)
| Window | n | win% | expectancy | profit factor | max DD (R) |
|---|---|---|---|---|---|
| **All** | 9,133 | 30.1% | **+0.171R** | 1.23 | −358 |
| In-sample | 4,566 | 28.6% | +0.104R | 1.14 | −358 |
| **Out-of-sample** | 4,567 | 31.6% | **+0.238R** | 1.33 | −197 |
| Random control | 9,133 | 50.2% | **−0.049R** | 0.94 | −514 |

## Reading the result
- Positive, **OOS stronger than IS**, and the random control is **negative** — so the "buy the
  stretch below the mean" signal beats coin-flip timing. Real mean-reversion edge on daily stocks.
- Same low-win / big-win shape as the trend strategies (win ~30%, target is the mean which is far).
- Large drawdown — catching falling knives clusters losses in bear regimes; a regime filter
  (e.g., only when SPY > its 200-MA) is the obvious next test.

## Caveats / next steps
- Only 1 of 4 primitives tested. **H-PA1** (big-body candle S/R) and **H-PA4** (fib-pullback depth)
  remain queued. Test a regime gate, an ATR-multiple sweep (2.0 / 2.5 / 3.0), and a volume-climax
  add-on (overlaps S6).
