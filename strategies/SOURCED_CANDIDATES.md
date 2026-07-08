# Sourced strategy candidates — queue for the backtest rig

Strategies sourced from the reviewed/curated platforms in `STRATEGY_SOURCES.md`. Each must pass the
same rig as everything else — **OOS PF ≥ ~1.2, avg-R > 0, ≥ ~100 trades, beats its random-direction
control** — and then the correlation gate vs the live book, before it's wired (`active:false`).
Reported stats below are the *source's* claims (our prior), NOT our validation.

## Queue

| # | Candidate | Family / style | Source (reviewed) | Rules (mechanical) | Reported | Status |
|---|---|---|---|---|---|---|
| 1 | **IBS mean-reversion** | mean-rev / swing (1–4d) | QuantifiedStrategies; Pagonidis (2013) NAAIM paper; Alvarez Quant | IBS = (close−low)/(high−low). Long when **IBS<0.2**; exit when **IBS>0.8** or after N days. Optional trend (close>SMA200) / volume filter. | Pagonidis: IBS<0.2 → next-day **+0.35%**; IBS>0.8 → −0.13%. Works on indices/liquid stocks. | ⚠️ **MARGINAL** — OOS PF 1.16 (best), below 1.2; beats control (0.87), 58% win. Corr 0.44 (diverse) but edge doesn't clear on broad single stocks (source says it's an *index/ETF* effect). `scripts/bt_ibs.py`. Revisit on an ETF/index universe. |
| 2 | **Turn-of-the-Month** | seasonality / calendar | QuantifiedStrategies; Quantpedia | Enter at close on the **5th-last trading day**; exit at close on the **3rd trading day** of the new month. | SPY CAGR 2.87%, MaxDD 12%, ~25% exposure; works internationally. | ✅ **PASS + DIVERSIFIER** — OOS PF **1.28** (IS 1.35), +0.11R, 53% win, n=173k, beats control 0.92; **max corr to live 0.36** (seasonality is orthogonal to the trend/mean-rev book). `scripts/bt_tom.py`, `bt_tom_corr.py`. Ready to wire (`active:false`) pending human review. |
| 3 | Overnight anomaly | session / anomaly | Quantpedia; Alpha Architect; Elm Wealth | Buy at close, sell at next open (Mon/Tue/Thu variant). | Most S&P gains are overnight — **BUT** Alpha Architect: "trading costs wipe out" it; OHLC data-artifact risk. | deprioritized (cost-fragile; needs close/open exec) |

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
