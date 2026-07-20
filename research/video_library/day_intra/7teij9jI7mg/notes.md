# 7teij9jI7mg

Status: PENDING — spec extracted, awaiting backtest (PF>=1.3 bar).

{
  "instrument": "Liquid equities/indices (SPY,QQQ,TSLA), ES/NQ futures",
  "timeframe": "15m opening range, 5m execution",
  "session": "first 15 min RTH then intraday",
  "direction": "both",
  "indicators": "Opening range (first 15m = 3x 5m candles), volume",
  "entry_trigger": "Mark high/low of first 15 min. Wait for a 5m candle to CLOSE beyond the range (confirms direction). Then wait for a pullback/retest of the broken level; ENTER on rejection from the level with volume confirmation.",
  "filters": "Skip initial-breakout entries (wait for the retest). Volume/VPA confirmation on the rejection.",
  "stop": "Just beyond the opposite side of the opening range",
  "targets": ">=2R; take partials at 2R, move stop to BE, let runners run",
  "summary": "15m ORB + retest-rejection entry, stop=OR width, 2R+ runners (overlaps existing ORB research; check correlation)"
}

## Backtest result (scripts/backtest_prospects.py, orb_retest)
- FX 5m, 2015-01-01 → 2025-03, IS<2022≤OOS, AUD/GBP/EUR pooled.
- **Gross:** OOS PF 1.11 · WR 42.8% · avgR +0.052 · N=1,885 (EURUSD OOS PF 1.23)
- **Net:** net of 0.7-pip cost: OOS PF 1.00 (breakeven)
- Baseline: control_with_trend OOS PF 0.97 net 0.85
- **Verdict: PENDING** — Mechanical backtest as an FX stand-in (London-open opening range, 5m, 2015-2025): OOS PF 1.11 gross / 1.00 net, WR 43%, ~1,885 trades — the only prospect that holds breakeven net and clearly beats the control; EURUSD OOS PF 1.23 gross. Still under the 1.3 bar. It is equity/index-native (SPY/QQQ/ES) and we have no cached 5m equity data — needs a faithful RTH-equity re-test before a verdict. KEEP pending.
