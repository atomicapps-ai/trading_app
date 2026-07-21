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

## ORB hunt follow-up
- Basic-ORB parameter hunt (scripts/hunt_orb.py) on gold/euro/major FX 5m: best config (EURUSD, London open, 30m range, R:R 1.5) reached OOS net PF 1.18 but per-year stability shows it is REGIME-DEPENDENT — net-losing in-sample 2015-2021 (2018 PF 0.72, 2019 0.78), positive only in the 2022-2025 OOS window. Full-period net ~breakeven. Never clears PF>=1.3. No robust FX edge. Equity-native RTH re-test remains the only (low-priority) way it could be salvaged.
- Full sweep + per-year table: research/video_library/ORB_HUNT.md

## Equity-native re-test — CLOSES the PENDING verdict (2026-07-20)

The "no cached 5m equity data" blocker was false: `data/historical/` holds 21 years of
RTH 5m bars for SPY / QQQ / IWM / DIA (~421k each, 2005-01-03 → 2026-07-07). Re-tested on
the native instrument via `python -m scripts.bt_equity_open_setups`:

- 09:30 ET opening range (DST-aware), **entry at the next bar's open** (not the signal
  bar's close), flat 15:55 ET, 2bp round-turn cost, stop resolved first when a bar
  touches both stop and target.
- Control = the identical strategy with the **direction randomised**, 5 seeds — the only
  control that isolates predictive skill from payoff geometry.

| scope | N | WR% | PF |
|---|--:|--:|--:|
| FULL (2005-2026) | 14,664 | 42.7 | 0.937 |
| IS (<2016) | 7,473 | 41.2 | 0.895 |
| OOS (≥2016) | 7,191 | 44.2 | **0.984** |
| **control OOS** | — | — | **0.986** |

Per-year PF: 0.82 0.98 0.78 1.18 0.63 0.98 1.09 0.88 0.88 0.80 0.87 0.84 0.92 0.93 1.07
0.99 0.99 1.08 1.06 0.98 1.04 0.94 — oscillates around the control, no IS/OOS drift.

**Trade-chart verification** (`python -m scripts.build_equity_review --strategy orb_retest`):
winners and losers were inspected individually. The opening-range box, the break, the
retest of the broken level, the stop on the far side of the range and the 2R target all
match `spec.json`. The mechanics are faithful — **the setup simply has no directional
content.** The FX stand-in was not what killed it.

**Verdict: PENDING → REJECTED.** See `research/video_library/PROCESS_AUDIT.md`.
