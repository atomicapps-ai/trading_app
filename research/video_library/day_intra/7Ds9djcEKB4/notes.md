# 7Ds9djcEKB4

Status: PENDING — spec extracted, awaiting backtest (PF>=1.3 bar).

{
  "instrument": "FX majors + liquid equities",
  "timeframe": "5m/15m (intraday); creator demoed 4H",
  "session": "RTH / any",
  "direction": "both",
  "indicators": "50 EMA, Chandelier Exit (ATR trailing stop)",
  "entry_trigger": "LONG: price below 50EMA, then a candle CLOSES back above 50EMA (reclaim); wait for a pullback of >=2 consecutive red candles; draw a horizontal line at the swing high before the pullback; BUY when a candle BODY closes above that line. SHORT = mirror below 50EMA.",
  "filters": "Invalid if the pullback closes back below the 50EMA before the line breaks. Skip if the breakout candle is >3-4x the average candle size (unsustainable).",
  "stop": "Chandelier Exit level (ATR-based)",
  "targets": "2R (2x stop distance), fixed",
  "summary": "50-EMA reclaim + micro-pullback breakout continuation, ATR chandelier stop, 2R target (creator claim 65% WR, unverified)"
}

## Backtest result (scripts/backtest_prospects.py, ema_reclaim_pullback)
- FX 5m, 2015-01-01 → 2025-03, IS<2022≤OOS, AUD/GBP/EUR pooled.
- **Gross:** OOS PF 0.95 · WR 34.1% · avgR -0.045 · N=10,260
- **Net:** net of 0.7-pip cost: OOS PF 0.86 · avgR -0.114
- Baseline: control_with_trend OOS PF 0.97 net 0.85
- **Verdict: REJECTED** — Mechanical backtest (FX 5m AUD/GBP/EUR, 2015-2025): OOS PF 0.95 gross / 0.86 net, WR 34%, ~10,260 trades — net loser, worse than a fixed-2:1 with-trend control. The ATR-chandelier stop + 2R target bleeds out. Reject.
