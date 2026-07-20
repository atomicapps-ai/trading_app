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
