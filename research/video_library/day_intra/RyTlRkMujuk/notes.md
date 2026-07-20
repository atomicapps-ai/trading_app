# RyTlRkMujuk — Three-Line Strike (FX intraday continuation)

**Verdict:** CANDIDATE — spec extracted, awaiting in-app PF >= 1.3 backtest.

## Why kept
- Fully **mechanical** and novel vs the current book — we have no three-line-strike
  detector. Entry, stop, and target are all fixed and unambiguous.
- Fits the "payoff geometry" thesis: fixed 2:1, cut at 10 pips, with-trend only.
- FX 5m — directly in scope for the intraday/FX push.

## Exact rules
- Trend by market structure (HH/HL up, LH/LL down); flip on a structure break.
- Uptrend: 3 green candles + 1 bearish engulfing pullback -> LONG at engulfing close.
- Downtrend: mirror. Wait for candle close; skip counter-trend strikes.
- Skip if the engulfing candle > 10 pips (stop discipline). Stop 10p, target 20p.

## Backtest notes for validation
- Creator claims ~70-75% WR on AUDUSD/GBPUSD, London 06:00-10:00 London time.
- Run across sessions + pairs; report which session/pair holds up OOS.
- Watch for repainting: "engulfing" must be judged on closed candles only.
- Correlation-gate vs the live/candidate book before wiring.

## Backtest result (scripts/backtest_prospects.py, three_line_strike)
- FX 5m, 2015-01-01 → 2025-03, IS<2022≤OOS, AUD/GBP/EUR pooled.
- **Gross:** OOS PF 1.01 · WR 38.1% · avgR +0.003 · N=9,887 (full N=31,197, PF 1.00)
- **Net:** net of 0.7-pip cost: OOS PF 0.89 · avgR -0.067
- Baseline: control_with_trend OOS PF 0.97 net 0.85
- **Verdict: REJECTED** — Mechanical backtest of the extracted spec (FX 5m AUD/GBP/EUR, 2015-2025): OOS PF 1.01 gross / 0.89 net (0.7-pip cost), WR 38%, ~9,900 trades — below the 1.3 bar and net-negative after realistic spread. Only marginally beats the with-trend control. Creator's ~70-75% WR claim did not hold (mechanical WR 38% at 2:1). Reject for live wiring.
