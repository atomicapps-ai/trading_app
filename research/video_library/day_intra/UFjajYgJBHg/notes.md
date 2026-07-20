# UFjajYgJBHg — ORB / "9:30am" 10-year backtest study (EVIDENCE, not a strategy)

**Verdict:** REJECTED as a tradeable setup (it's meta-analysis of ORB variants we
already research). Kept as **external corroboration** of our OOS thesis.

## What it is
Creator coded the popular "9:30am / opening-range-breakout" guru variants (Casper
retest, Scarface retest-candle-shape, FVG, J-Dub 5m-range/1m-entry) and backtested
them over 10y on ES, NQ, gold, euro futures **with NinjaTrader commissions + 1.5-tick
slippage**, then swept 90k parameter combinations.

## Findings that matter to us
- Every "guru secret" (retest / FVG / candlestick confirmation) was a **net loser OOS**
  with realistic costs (ES -66%, gold -50%, euro -97%, Scarface -98% over 10y). The
  1-month backtests the gurus showed were cherry-picked to the month before posting.
- The **basic ORB** (limit at range edge on breakout, no confirmation) **beat all the
  "secret" variants** on the assets where ORB worked at all.
- Best assets were **euro (+630%/5y) and gold (+431%/5y)**; **ES/NQ couldn't beat
  buy-and-hold** even with best params.
- Best **R:R was < 1:2** (not the guru-standard 2:1).
- Best **range timeframe was 15m/10m**, not 5m; entry TF higher than 1m.
- Best params differ per asset — one setup does NOT generalize across instruments.

## Relevance
- Reinforces our "edge doesn't generalize" pivot and the reject-the-ORB-noise stance.
- Directly supports the deferred **fvg_continuation gold/FX** direction: FX + metals
  are where opening-range edges actually showed up, not index futures.
- If we ever wire a basic ORB, prefer euro/gold, 15m range, R:R < 2:1, per-asset tuned
  — and treat per-asset overfitting as the main risk.
