# Sourced strategy candidates — queue for the backtest rig

Strategies sourced from the reviewed/curated platforms in `STRATEGY_SOURCES.md`. Each must pass the
same rig as everything else — **OOS PF ≥ ~1.2, avg-R > 0, ≥ ~100 trades, beats its random-direction
control** — and then the correlation gate vs the live book, before it's wired (`active:false`).
Reported stats below are the *source's* claims (our prior), NOT our validation.

## Queue

| # | Candidate | Family / style | Source (reviewed) | Rules (mechanical) | Reported | Status |
|---|---|---|---|---|---|---|
| 1 | **IBS mean-reversion** | mean-rev / swing (1–4d) | QuantifiedStrategies; Pagonidis (2013) NAAIM paper; Alvarez Quant | IBS = (close−low)/(high−low). Long when **IBS<0.2**; exit when **IBS>0.8** or after N days. Optional trend (close>SMA200) / volume filter. | Pagonidis: IBS<0.2 → next-day **+0.35%**; IBS>0.8 → −0.13%. Works on indices/liquid stocks. | ⚠️ **MARGINAL both universes** — broad stocks OOS PF 1.16; 13 cached **ETFs** OOS PF 1.12 (IS 1.14, 60% win, ctrl 0.77). Beats control, consistent IS/OOS, but doesn't clear 1.2. Sources highlight **QQQ** (not cached) — worth a re-test once QQQ/more index ETFs are fetched. `scripts/bt_ibs.py`, `bt_etf_universe.py`. Held. |
| 2 | **Turn-of-the-Month** | seasonality / calendar | QuantifiedStrategies; Quantpedia | Enter at close on the **5th-last trading day**; exit at close on the **3rd trading day** of the new month. | SPY CAGR 2.87%, MaxDD 12%, ~25% exposure; works internationally. | ✅ **PASS + DIVERSIFIER** — OOS PF **1.28** (IS 1.35), +0.11R, 53% win, n=173k, beats control 0.92; **max corr to live 0.36** (seasonality is orthogonal to the trend/mean-rev book). `scripts/bt_tom.py`, `bt_tom_corr.py`. Ready to wire (`active:false`) pending human review. |
| 3 | Overnight anomaly | session / anomaly | Quantpedia; Alpha Architect; Elm Wealth | Buy at close, sell at next open (Mon/Tue/Thu variant). | Most S&P gains are overnight — **BUT** Alpha Architect: "trading costs wipe out" it; OHLC data-artifact risk. | deprioritized (cost-fragile; needs close/open exec) |

## Batch 2 (2026-07) — tested, not promoted

| Candidate | Family | Source | Result | Verdict |
|---|---|---|---|---|
| **Double-7s** (Connors/Alvarez) | mean-rev | QuantifiedStrategies / *Short Term Trading Strategies That Work* | close>200MA, buy 7-day low, sell 7-day high. Stocks OOS PF **1.16** (IS 1.38); ETFs OOS **1.01** (IS 1.52). | ⚠️ **reject** — classic IS→OOS decay (simple mean-reversion faded post-2010); also overlaps our RSI mean-rev family. `scripts/bt_sourced_batch2.py` |
| **Halloween / Sell-in-May** | seasonality (beta overlay) | QuantifiedStrategies / Quantpedia | Long Nov→Apr, flat May→Oct. Stocks OOS PF **2.42**, +1.96R, 67% win, n=14k; ETFs 3.37. | ⚠️ **hold — beta-timing, not alpha.** The huge R is just the 6-month equity drift; it's long-market exposure with a seasonal switch, so it beats a short-flipped control only because stocks rise, and it correlates with the long book by construction. Real effect, but needs a **market-neutral / excess-vs-buy-&-hold** framing before it's treated as a diversifier. Same caveat class as `ma_crossover`. |

## Backlog to source next (distinct families preferred)

- **Connors TPS / cumulative-RSI** (mean-rev — likely overlaps our RSI Pullback; low priority)
- **Bollinger %b mean-reversion** (overlaps Band Extreme Fade)
- **52-week-high / dual-momentum / sector-rotation** (trend — check corr vs Momentum Breakout)
- **Larry Williams %R**, **VIX-timed SPY mean-reversion** (regime)
- Verified-track-record leaderboards (Collective2 / Darwinex / Composer) → reverse-engineer the
  long-track-record, low-drawdown systems into hypotheses.

## Notes
- IBS and Turn-of-the-Month are the priority: both are **distinct families** from the live book
  (IBS = close-in-range trigger, not RSI; TOM = calendar), so if they validate they likely pass the
  correlation gate as genuine diversifiers.
- Both have no natural hard stop → tested with a fixed nominal-risk normalization (as with the
  Connors RSI Pullback / presidential-cycle), so profit-factor/win% equal the true dollar figures.
