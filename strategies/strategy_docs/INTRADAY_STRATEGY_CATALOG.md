# Intraday / day-trade strategy catalog — everything discovered & tested (2026-07-08)

Every strategy here is a **day trade**: enters and exits the **same session, flat by the close** — distinct
from the sourced *swing* candidates (IBS, Turn-of-Month, Double-7s…) in `SOURCED_CANDIDATES.md`, which hold
multiple days and are NOT day trades. Nothing below is `active` — none has cleared the PASS bar
(**OOS net PF ≥ 1.2, avg-R > 0, n ≥ ~100, beats random-direction control**).

Three test harnesses + one wired scaffold:
- `scripts/bt_intraday_research.py` — original 30-min kernels (Group 1)
- `scripts/bt_intraday_momentum.py` — academic Gao intraday-momentum (Group 2)
- `scripts/bt_intraday_families.py` — the 4-family 20-year deep test (Group 3)
- `strategy_configs/intraday_reversion.yaml` — the wired plumbing example (Group 4)

Cost: per-symbol round-trip from `cost_model.py` (SPY/QQQ ≈ 1.5 bps … thin ≈ 12 bps). "gross" = cost off.

---

## GROUP 1 — Original 30-minute kernels (`bt_intraday_research.py`)
Universe: 60–80 US stocks, ~5-yr 30-min bars (Alpaca). Entry = next-bar open, one trade/session, flat 15:00 ET.
Mean-reversion stops are **wide** = `mult × dailyATR%` so intraday noise doesn't stop you before the target.

| ID | Trade definition | Config values | Result (OOS) | Verdict |
|---|---|---|---|---|
| **vwap_revert_base** | In daily uptrend (close>SMA200), when price is ≥`stretch`% below session VWAP inside the entry window, buy next open, target = VWAP, wide stop. | stretch=0.7%, stop_mult=0.6×ATR, entry window 10:30–14:00, trend=on | net PF 0.54 / gross 0.96–0.98, 46% win | dead |
| **gap_fade_1_3_full** | Fade a morning gap-DOWN back toward prior close (long). Target = full prior close. | gap 1.0–3.0%, stop_mult=0.6×ATR, target_frac=1.0, trend=off | net 0.81 / **gross 1.07**, 50% win | best gross, still dead net |
| **gap_fade_1_3_half** | Same, target = halfway to prior close. | gap 1.0–3.0%, target_frac=0.5 | net 0.71 / gross 1.03, 55% win | dead |
| **gap_fade_1_3_full_trend** | gap_fade_1_3_full + require close>SMA200. | + trend=on | ≤ base | dead |
| **gap_fade_1_3_half_trend** | half-fill + trend filter. | + trend=on | ≤ base | dead |
| **gap_fade_05_2_half** | Smaller gaps, half fill. | gap 0.5–2.0%, target_frac=0.5 | net ~0.61 / gross 0.93 | dead |
| **gap_fade_2_5_full** | Larger gaps, full fill. | gap 2.0–5.0%, target_frac=1.0 | net 0.87 / gross 0.97, 45% win | dead |
| *k_rsi2_bounce* (defined, not in final sweep) | RSI(2)<`lo` below VWAP → long, target VWAP. | lo=10, stop_mult=0.6, window 10:30–14:00, trend=on | OOS PF 0.19–0.44 | dead |
| *k_orb_fade* (defined) | Failed breakdown of opening range → long back in. | or_bars=2 (first 2 bars = range) | OOS PF 0.19–0.44 | dead |
| *k_orb_breakout* (defined) | Break ABOVE opening range, target = range height. | or_bars=2, trend=on | OOS PF 0.19–0.44 | dead |

Shared floor: `MIN_RF=0.001` (skip absurdly tiny stops). Full numbers: `INTRADAY_FINDINGS.md`.

---

## GROUP 2 — Academic: Market Intraday Momentum (Gao, Han, Li & Zhou, JFE) — `bt_intraday_momentum.py`
Universe: 4 ETFs (SPY/QQQ/IWM/DIA) + 10 mega-cap stocks, 5-min bars. No stop → 5% nominal-R.

| ID | Trade definition | Config values | Result | Verdict |
|---|---|---|---|---|
| **intraday_momentum base** | Predictor r1 = first-30-min close ÷ prior daily close − 1. At 15:30 go LONG if r1>0 else SHORT; exit at close. | first window <10:00, last window ≥15:30, predictor=r1 | ETFs+stocks: gross OOS PF 0.96 / net 0.79 / ctrl 0.98 | dead (decayed) |
| **intraday_momentum enh** | Predictor = r1 + r12 (r12 = the 15:00–15:30 half-hour return). Same entry/exit. | predictor=r1+r12 | 4 ETFs: gross 0.95 / net 0.71 / ctrl 1.00 | dead (decayed) |

Note: paper studied 1993–2013; anomaly ~halves post-publication (McLean–Pontiff). Re-confirmed decayed — see Group 3 D3 for the 20-year re-test.

---

## GROUP 3 — 4-family 20-year deep test (`bt_intraday_families.py`)
Universe: **9 ETFs with full 2005→2026 history** (SPY, QQQ, IWM, DIA, XLK, XLF, XLE, XLV, XLI), pooled,
~48k symbol-days. Fair per-symbol cost, chronological IS/OOS half-split, random control. C uses a 3% cat-stop
(R=3%); A & D have no stop (R=5% nominal).

### Family A — Overnight vs intraday split
| ID | Trade definition | Config values | Result (20y pooled) | Verdict |
|---|---|---|---|---|
| **A1 overnight_hold** | Buy at the close (15:59), sell at next open (09:30). Long the overnight session. | none (baseline); cost = 1.5× per-symbol RT (auction) | **gross PF 1.17** / net 1.01 / OOS 1.02 / ctrl 1.02 | real gross, **washes net** |
| **A2 intraday_short** | Short at open, cover at close (the mirror — falsification of the split). | none | net 0.85, avgR −0.012 | correctly negative ✓ |
| **A3 overnight_conditional** | Buy close→next open ONLY when prior-day intraday return < 0, 20-day realized-vol percentile < 0.6, and next open is NOT a Monday. | prior_intraday<0, rv_pct<0.6, skip Fri→Mon | gross 1.23 / net 1.00 / OOS 0.97 (passed SPY-only OOS 1.25) | washes pooled |

### Family B — Regime-conditioned kernels
| ID | Trade definition | Config values | Result | Verdict |
|---|---|---|---|---|
| **B1 gapfade_highvol** | Fade a 1–3% gap toward prior close, but only when 20d-realized-vol pct ≥ 0.6 AND the gap is counter-trend (gap-down while >SMA200, or gap-up while <SMA200). | gap 1–3%, rv_pct≥0.6, counter-trend, stop 1.5%, target=prior close | net 0.86 / OOS 0.89 / ctrl 1.01 | dead |
| **B2 orb_trend_hvol** | ORB-30 breakout LONG only, gated: symbol>SMA200 AND opening-30m volume ≥ 20-day slot median. | ORB 09:30–10:00 range, uptrend, vol≥slot-median, target=range height, stop=−range | net 0.78 / OOS 0.83 / ctrl 0.95 | dead |

### Family C — Opening-range / first-hour (30-min bars)
Conviction candle = body ≥ 50% of range AND (bull: close in top 40% of range / bear: close in bottom 40%) AND volume ≥ 20-day slot median.
| ID | Trade definition | Config values | Result | Verdict |
|---|---|---|---|---|
| **C1 opening_conviction** | Classify the 09:30–10:00 30-min bar; if a conviction candle, enter its direction at 10:00 open, exit EOD, 3% cat stop. | body≥50%, close-pos≥0.6/≤0.4, vol≥slot-median, EOD exit, 3% stop | gross 1.14 / net 1.06 / **OOS 0.95** | gross edge, decays OOS |
| **C2 opening_double_lock** | Both 09:30 and 10:00 bars are same-direction conviction candles → enter at 10:30, EOD, 3% stop. (Honest 20-yr re-test of the removed `double_lock`.) | two consecutive conviction candles, 3% stop, EOD | net 0.96 / OOS 0.94 | dead (DL removal vindicated) |
| **C3 orb_breakout** | Stop-entry on first break of the 09:30–10:00 range; target = 1× range height; stop = opposite edge; EOD backup. | or window 09:30–10:00, target=+1R range, stop=opposite edge | net 0.90 / OOS 0.91 | dead |

### Family D — Time-of-day / last-hour
| ID | Trade definition | Config values | Result | Verdict |
|---|---|---|---|---|
| **D1 last_hour_momentum** | At 15:00, if day return (open→15:00) > +0.3% go long / < −0.3% go short; exit at close. | threshold ±0.3%, 15:00 entry, close exit | gross 1.11 / net 0.95 / OOS 0.91 | net coin-flip |
| **D3 first30_to_last30** | The Gao re-test on 20 years: at 15:30 long/short by sign of first-30-min return vs prior close; exit close. | first<10:00, last≥15:30 | gross 1.11 / net 0.88 / **OOS 0.75** | **decayed further on deep data** |
| **D4 power_hour_reversal** | At 15:30, take the OPPOSITE of the 09:30→15:30 move, but only on top-tercile |move| days; exit close. | reverse day move, |move| ≥ 66th pctile | net 0.74 / OOS 0.81 | dead |

Raw split confirmation (20y daily means): overnight +0.03–0.05%/day vs intraday +0.00–0.02% every ETF; **IWM intraday negative** (−0.005%). The split is real; it just doesn't net-clear cost at daily ETF frequency.

---

## GROUP 4 — Wired scaffold (plumbing only, not an edge)
| ID | Trade definition | Config values | Status |
|---|---|---|---|
| **intraday_reversion** (`strategy_configs/intraday_reversion.yaml`) | 30-min VWAP mean-reversion: in daily uptrend, buy `stretch_pct`% below session VWAP, flat by session close via TimeStop. | min_bars=3, stretch_pct=0.5, stop_buffer_pct=0.1, require_trend=true; risk: max_risk_pct_per_trade=0.40, max_position_pct=6.0, min_rr=1.0; style=day_trade, family=mean_reversion, time_stop 15:00 ET | **active:false** — exists only to prove the day-trade path end-to-end (detector→intraday workflow→same-day TimeStop→executioner flatten). Never validated. |

---

## Bottom line
- **~20 distinct day-trade strategies tested**; **zero clear the PASS bar.**
- Best *gross* edges: gap_fade_1_3_full (1.07), and the overnight split A1 (1.17) — both die on cost.
- The overnight/intraday split is the only **structurally real** effect found; net-marginal on ETFs.
- Crowded kernels (VWAP-revert, gap-fade, ORB, opening-conviction, intraday-momentum) are dead net even on
  20 years and even regime-conditioned → not a data-depth artifact.
- **Open lead (pending full 102-symbol pull):** single-stock + selective overnight (Family A per-stock on
  smaller/lower-priced names, and hold only high-conviction nights) — the one variant with a real shot at net > 1.2.
