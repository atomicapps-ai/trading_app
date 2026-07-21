# Prospect strategy backtest — day_intra video-mining candidates

**Run:** `scripts/backtest_prospects.py` · FX 5m · 2015-01-01 → 2025-03-21 ·
IS < 2022-01-01 ≤ OOS · pooled over AUDUSD, GBPUSD, EURUSD · single-position
model, intra-bar stop/TP via `agents/detectors/external/_base.py`.

**PASS bar:** PF ≥ 1.3, avg-R > 0, ~100+ trades, beats the with-trend control,
corr < 0.60 to the live book.

Each detector is a **mechanical interpretation** of the spec I extracted from the
video. Where the creator was discretionary ("clean structure", "support/resistance
zone", "market structure"), I chose a precise, defensible proxy (50-EMA for trend,
session ranges for AMD, opening-range levels for ORB). A discretionary human version
may differ — but the burden of proof is on the setup, and a mechanical version is
exactly what we'd need to wire one live.

## Results — OOS (out-of-sample, 2022→2025), pooled 3 majors

| Strategy | Video | N | WR% | PF gross | PF net¹ | avg-R | Verdict |
|---|---|--:|--:|--:|--:|--:|---|
| orb_retest | 7teij9jI7mg | 1,885 | 42.8 | **1.11** | 1.00 | +0.05 | ⏸ pending (equity-native) |
| three_line_strike | RyTlRkMujuk | 9,887 | 38.1 | 1.01 | 0.89 | +0.00 | ❌ reject |
| amd_session_reversal | Bdgev1or-7M | 1,533 | 37.5 | 0.95 | 0.87 | −0.03 | ❌ reject |
| ema_reclaim_pullback | 7Ds9djcEKB4 | 10,260 | 34.1 | 0.95 | 0.86 | −0.05 | ❌ reject |
| _control_ with-trend 2:1 | — | 11,543 | 39.3 | 0.97 | 0.85 | −0.02 | baseline |

¹ **PF net** deducts a 0.7-pip round-turn spread+commission per trade — a *tight*
retail cost on majors. On 10–20-pip scalps this is decisive.

## Verdict

**None of the four clears PF ≥ 1.3.** Even *gross* of costs, only `orb_retest`
(the equity-native strategy, run here on FX as a stand-in) and a barely-positive
`three_line_strike` beat 1.0 — and once a realistic 0.7-pip cost is applied, only
`orb_retest` holds breakeven while everything else turns net-negative.

- **three_line_strike** — the creator's ~70–75% WR claim did not survive: mechanical
  WR is 38% at a fixed 2:1, i.e. essentially the coin-flip a 2:1 payoff implies.
  Net-negative. Reject.
- **ema_reclaim_pullback** and **amd_session_reversal** — net losers, worse than the
  naive with-trend control. Reject.
- **orb_retest** — the lone survivor at breakeven-net (EURUSD OOS PF 1.23 gross). It is
  SPY/QQQ/ES-native, so this FX stand-in was not a faithful test and it was kept
  **pending** an RTH-equity re-run. **That re-run has now happened and closes it as a
  rejection** — see the correction below.

This is consistent with the whole intraday pass and with the **UFjajYgJBHg** evidence
video (10-yr cost-adjusted ORB study): opening-range / EMA / session scalps do not
survive out-of-sample once transaction costs are honest.

## CORRECTION (2026-07-20) — the "equity data gap" was false; orb_retest is now rejected

This page claimed the project had **no cached 5m equity data**. It does: 522 `*_5m.csv`
files, including **21 years of RTH bars for SPY / QQQ / IWM / DIA** (2005-01-03 →
2026-07-07, ~421k bars each). The FX stand-in was never necessary.

Re-tested on the native instrument via `scripts/bt_equity_open_setups.py` — 09:30 ET
anchor, **entry at the next bar's open**, flat 15:55 ET, 2bp round-turn cost, stop
resolved first when a bar touches both stop and target, and a control that is the same
strategy with the **direction randomised** (5 seeds):

| detector | N | WR% | OOS PF | matched control | verdict |
|---|--:|--:|--:|--:|---|
| orb_retest | 14,664 | 42.7 | **0.984** | 0.986 | ❌ reject — no edge |
| false_break_fade | 40,483 | 36.8 | 0.750 | 0.751 | ❌ reject — no edge |
| opening_range_fade (fair geometry) | 7,168 | 39.2 | 0.890 | 0.877 | ❌ reject — no edge |

`orb_retest` per-year PF across 21 years oscillates around its control and never
establishes a trend (0.63 – 1.18, no IS/OOS drift). Trades were rendered and inspected
individually (`python -m scripts.build_equity_review --strategy orb_retest`): the opening
range, the break, the retest, the stop on the far range side and the 2R target all match
`7teij9jI7mg/spec.json`. **The mechanics are faithful and the setup has no directional
content** — this is a strategy verdict, not a harness artifact. `orb_retest` moves from
PENDING to REJECTED.

Note also that the `control_with_trend` used on this page is a fixed 10/20-pip geometry
while the detectors use ATR-scaled stops, so "beats the control" comparisons above are
not like-for-like. See `PROCESS_AUDIT.md` §D1.

## Caveats / how to push further
- **Costs dominate.** Re-run with `--cost-pips` to see the sensitivity; anything under
  ~PF 1.3 gross is unlikely to net out on a sub-20-pip target.
- **No parameter search.** These are the creators' stated parameters. `orb_retest` is
  the only one that looked worth a sweep — the equity re-test above removes the reason to
  run one.

Reproduce:
```bash
python -m scripts.backtest_prospects --since 2015-01-01 --oos 2022-01-01 \
    --pairs AUDUSD,GBPUSD,EURUSD                # gross
python -m scripts.backtest_prospects --cost-pips 0.7   # net of a tight retail spread
```
