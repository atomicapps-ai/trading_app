# S8 — Presidential-Cycle Seasonality

**Source video:** j8Q3MIwGYOk (strategy #1, citing Druckenmiller). **Family:** macro seasonality.
**Data fit:** index/stocks daily ✅. **Verdict: ❌ NOT SUPPORTED in our data.**

## The claim
"Buy the market ~2 years before a US general election, sell in the election year." The video shows
positive returns nearly every cycle since 1980 (only 2004 broke even) and notes 2026→2028 as the
next buy window.

## How we tested it
- **Headline (SPY):** return from January of (election−2) to November of the election year, per cycle.
  *Limitation:* our SPY cache starts April 2006, so only the 2024 cycle has both endpoints.
- **Robustness (pooled):** across all 90 stocks, compare the mean return of every **pre-election 2-yr
  window** to the mean of **all overlapping 2-yr windows** (2007–2024). If the cycle effect is real,
  pre-election windows should outperform.

## Backtest configuration
Universe SPY + 90 daily stocks · 2006–2026 · 2-year holding windows · returns in % (not R — this is
buy-and-hold, no stop, so the R/control framework doesn't apply).

## Results
| Measure | Value |
|---|---|
| SPY 2024 cycle (only complete one) | +33.9% |
| Pre-election 2-yr windows, pooled mean (n=298) | **+26.0%** |
| All 2-yr windows, pooled mean (n=1,327) | **+63.6%** |

## Reading the result
- In our 2006–2026 sample, **pre-election 2-yr windows underperformed the average 2-yr window**
  (+26% vs +64%). The cycle "buy-2-years-out" rule did *not* confer an edge here — if anything the
  opposite. (The high all-window mean reflects the 2009–2024 bull; the point is the cycle windows
  weren't special within it.)
- The single complete SPY cycle (2024, +34%) looks great in isolation but **n=1 proves nothing** —
  exactly the survivorship/small-sample trap the video falls into.

## Caveats
- Our data only spans ~3 election cycles of stocks and 1 of SPY — far too few to test a 4-year cycle.
  The video's 1980-onward claim can't be confirmed or refuted without index data back to 1980
  (^GSPC / ^DJI). Until then: **unsupported, do not trade.** A proper test needs long index history.
