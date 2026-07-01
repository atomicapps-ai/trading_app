# S9 — Fib Golden-Zone + Fair-Value-Gap Confluence

**Source videos:** j8Q3MIwGYOk#3, sZFdrxdVTMk. **Family:** confluence reversal.
**Data fit:** intraday/daily. **Verdict: ⏳ PENDING (quick-pass deferred).**

## The strategy (plain rules)
Draw a Fibonacci over the last swing. The **golden zone** (0.618–0.79) is where reversals are most
likely. Improve the edge by requiring a **same-direction fair-value-gap inside the golden zone** —
only take the reversal where fib and FVG align. Stop beyond the zone, target the prior swing.

## Why deferred
This is the **confluence claim** (H-FIB1 / H-ICT5) — the proposition that *stacking* fib + FVG beats
either alone. It's the most interesting untested idea in the library, but testing it properly means:
(1) it's intraday-native (1m FX/futures), same regime caveat as S3; and (2) it requires the
confluence-stack machinery (fib auto-fit on swings + FVG detection + alignment test) that the daily
harness doesn't yet implement. Rather than ship a misleading half-version on stock 15m, it's queued.

## Planned backtest configuration
- Detect swing legs (3-bar fractals) → fib 0.618–0.79 zone. Detect FVGs (3-bar gaps). Trigger:
  price retraces into golden zone AND a same-direction FVG overlaps it. Stop beyond zone; target
  prior swing extreme. Compare **fib-alone vs FVG-alone vs fib+FVG confluence** (the actual question).
- Run on 15m stocks first (flagged), then on FX intraday once available. IS/OOS · costs · control.

## Note
S3's result is the relevant prior: the CHoCH/FVG triggers are coin-flips directionally; if fib+FVG
confluence is to add value, it must show up as a *filter* that raises expectancy over the base — that
is exactly what this test will measure. **Status: queued.**
