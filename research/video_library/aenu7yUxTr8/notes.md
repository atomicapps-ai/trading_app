# aenu7yUxTr8 — "Best indicator to build a strategy upon (100-year backtest)" (Financial Wisdom)

Source: <https://www.youtube.com/watch?v=aenu7yUxTr8>

## Rules (mechanical)
- **Meb Faber timing model** on the S&P 500 index: be long the index while monthly close is **above the 10-month moving average** (equivalently daily close above the 200-day MA); move to **cash** (earning ~T-bill) when it closes below. Re-enter on the next close back above.
- Long-only, single-instrument (or index) trend-timing overlay; no per-trade stop/target.

## Verdict: REJECT — valid but out of the rig's scope + already embodied by the regime gate.
This is a real, well-documented mechanical system (Faber 2013), but it's a **long-only index-timing overlay**, not a defined-risk swing setup: over a century it produces only a handful of regime switches per instrument and has no stop/target, so it cannot generate the ≥~100 defined-risk trades with per-trade R-multiples and OOS PF the pass bar requires. Its documented value is drawdown reduction on buy-and-hold (vol ~12% vs ~18%), not a high-PF trade edge. Crucially, its core insight — only be exposed when price is above the long-term MA — is **already deployed** in the live suite as the SPY>200-day-MA regime gate (momentum_breakout requires SPY>200MA; fear_dip_reversion keys off SPY<200MA/VIX). Nothing new to adopt as a standalone tradeable strategy.
Status: rejected
