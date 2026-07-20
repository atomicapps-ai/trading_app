# Bdgev1or-7M

Status: PENDING — spec extracted, awaiting backtest (PF>=1.3 bar).

{
  "instrument": "FX majors (EURUSD etc.)",
  "timeframe": "5m",
  "session": "New York session (execution); reads Asian + London sessions",
  "direction": "both (counter to London push)",
  "indicators": "Session ranges (Asian/London/NY), liquidity sweeps, engulfing candle, support/resistance zones",
  "entry_trigger": "AMD model: tight Asian range (accumulation) -> aggressive London push (manipulation) sweeps the Asian high or low -> expect NY-session REVERSAL (distribution) sweeping the other side. If London swept the Asian LOW -> look for BUYS on the NY reversal (and mirror). Entry model 1: at a support/resistance zone after the sweep, enter on a bullish/bearish ENGULFING candle.",
  "filters": "No trade if the Asian range is too wide (accumulation failed) or London gives no aggressive push (manipulation failed) -> switch pairs.",
  "stop": "Beyond the swept liquidity / zone",
  "targets": "opposite side of range / 2R (creator: 3 entry models tested 72-86% on 330 trades, unverified)",
  "summary": "ICT AMD: Asian range -> London sweep -> NY-session reversal, engulfing entry at S/R (FX 5m) \u2014 genuine FX intraday candidate"
}

## Backtest result (scripts/backtest_prospects.py, amd_session_reversal)
- FX 5m, 2015-01-01 → 2025-03, IS<2022≤OOS, AUD/GBP/EUR pooled.
- **Gross:** OOS PF 0.95 · WR 37.5% · avgR -0.034 · N=1,533
- **Net:** net of 0.7-pip cost: OOS PF 0.87 · avgR -0.133
- Baseline: control_with_trend OOS PF 0.97 net 0.85
- **Verdict: REJECTED** — Mechanical backtest of the ICT AMD spec (Asian 00-07 range -> London 07-12 sweep -> NY 12-17 engulfing reversal, FX 5m EUR/GBP/AUD, 2015-2025): OOS PF 0.95 gross / 0.87 net, WR 37.5%, ~1,530 trades — net loser. The creator's 72-86% / 330-trade claim did not reproduce mechanically. Reject. (A discretionary zone/HTF-bias version may differ, but the burden is on it.)
