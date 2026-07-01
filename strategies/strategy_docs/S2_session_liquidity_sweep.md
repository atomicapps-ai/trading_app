# S2 — Session Liquidity Sweep (NY open)

**Source video:** 8a3QNHOD7-I. **Family:** intraday session-liquidity reversal.
**Data fit:** FX/futures intraday ⚠️ (not validly testable on our data). **Verdict: ⏳ PENDING — needs FX data.**

## The strategy (plain rules)
Mark the Asia and London session highs/lows. At the **New York open (09:30 ET)**, wait for price to
**sweep** (take out) a London/Asia extreme, then trade the **opposite direction** to the other
session's liquidity (or a fixed 2:1/3:1). Entry trigger: first 5-min candle that **closes back**
through the swept level; stop beyond the sweep. Author claims this lifted his win rate ~35%→50%+.

## Why no results yet
The strategy is defined by **FX/futures trading sessions** (Asia / London / New York). US equities
trade a single ~6.5-hour session with overnight gaps — there is no clean Asia/London range to sweep,
so running this on our stock cache would be **meaningless**, not just regime-mismatched. Documenting
the configuration; deferring the run until intraday FX (e.g., EURUSD/GBPUSD) or index-futures
(NQ/ES) bars are available.

## Planned backtest configuration (when FX data is loaded)
- Instrument: NQ / EURUSD, 15m + 5m. Sessions via session-clock (Asia 18:00–03:00, London 03:00–
  09:30, NY 09:30+ ET). Entry: first 5m close back through swept London/Asia extreme. Stop beyond
  sweep extreme. Target: opposite session liquidity or fixed 2:1. IS/OOS split · costs · control.
- The transferable, testable core is **H-SW2**: does "first 5m retrace-candle close back" beat
  trading the raw level? (Same retest-vs-chase question as S1, which we *did* find positive.)

## Status: queued for the next session once intraday FX/futures data is fetched.
