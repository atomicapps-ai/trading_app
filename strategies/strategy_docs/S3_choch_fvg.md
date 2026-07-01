# S3 — Break-of-Structure / CHoCH + Fair-Value-Gap Retest (ICT/SMC)

**Source videos:** -4IPHZwse0M, sZFdrxdVTMk, Cj09mzu5_oU, j8Q3MIwGYOk#2 (the whole ICT/SMC family).
**Family:** structural break + FVG retest. **Data fit:** intraday — tested on 15m **stocks** (videos
trade 1-min FX/futures at NY open; strong regime-flag). **Verdict: directional trigger ❌; with
asymmetric payoff ⚠️ thinly positive.**

## The strategy (plain rules)
Higher-timeframe bias → a **change-of-character (CHoCH)**: a candle **closing** beyond the last swing
pivot (body close, not a wick) → enter on a retrace into the fair-value-gap / fib zone the break
created → stop beyond structure → let winners run to the next gap. Low win, high R:R.

## Precise definitions (as backtested)
- Swing pivots: 3-bar fractals. **CHoCH** = close beyond the last confirmed pivot (no look-ahead).
- **Direction test:** forward 8-bar return after the break, R = ATR(14).
- **Payoff test:** enter at break close, **stop at the opposite structure**, fixed target at 1:2 / 1:4.
- FVG = 3-bar gap (candle-1 wick vs candle-3 wick). Direction test run on FVGs too.

## Backtest configuration
10 symbols · 15-minute bars · chronological IS/OOS · ATR-normalized · random-direction control.
*(Separate intraday script, not the daily harness — quick-pass scope.)*

## Results
**Direction-only (8-bar forward, is the trigger predictive?)**
| Signal | n | win% | mean |
|---|---|---|---|
| CHoCH/BOS | 23,332 | 49.3% | −0.013R |
| FVG | 76,724 | 49.7% | +0.007R |
| Random control | 2,999 | 49.3% | −0.070R |

**Asymmetric payoff (CHoCH + structural stop + fixed target)**
| Rule | n | win% | expectancy | OOS expectancy |
|---|---|---|---|---|
| 1:2 | 23,274 | 34.2% | +0.027R | +0.025R |
| 1:4 | 23,247 | 21.3% | +0.066R | +0.087R |

## Reading the result
- **As a directional predictor, CHoCH and FVG are coin-flips** (≈49–50% win, ~0R, same as random).
  The ICT "signals" do not predict direction on this data.
- **The edge is purely payoff geometry:** structural stop + let winners run flips it to a small,
  OOS-stable positive (+0.066R at 1:4, 21% win). Same lesson as ORB (S1) and the R:R filter (S4).

## Caveats / next steps
- Native regime is 1-min FX/futures at NY open — untestable on our 15m stock cache; numbers are
  approximate. The **confluence stack** (fib 0.618 + FVG + liquidity inflection, H-ICT5) is the
  videos' real distinguishing claim and remains **untested** — it needs proper 1-min FX data.
