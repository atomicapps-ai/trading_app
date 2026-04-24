# VCP / Absorption at Resistance — Research Notes (ARCHIVED)

> **This detector has been superseded by the empirically-derived
> [`breakout_empirical.py`](../../agents/detectors/breakout_empirical.py)
> whose spec is in [`empirical_breakout.md`](empirical_breakout.md).**
>
> This document is preserved as the research record of the VCP
> theoretical-first approach. The empirical analysis on 502 labeled
> winners found that the strict VCP/absorption rubric captures only
> a narrow slice of real breakouts (flat ceiling + 3+ touches + vol
> dry-up + monotonic tightening). Only ~50% of winners have even
> one pivot high within 2% of their anchor price; half had volume
> at or above prior averages. The strict definition is one specific
> shape, not the general winner pattern.
>
> Keep this doc for: (1) history of the iteration path, (2) the
> narrative framing of the two-sided buyer-seller battle (still
> useful for interpretation even if the detector is broader now),
> (3) the SMCI and AVGO case studies that demonstrated the limits
> of canonical definitions.

---


Living notes on the Volatility Contraction Pattern detector, focused on
the **Absorption at Resistance** variant: flat ceiling, higher lows,
shrinking wedge into an apex, volume dry-up, breakout.

Prototype: Pine Script in TradingView, "VCP — Absorption at Resistance v2".
Production target: `agents/detectors/vcp_absorption.py` once parameters
validate across ≥5 textbook examples.

---

## 1. The pattern as a narrative — two sides at war

Every absorption pattern is a **multi-month battle between supply and
demand at a known price level**. Reading it as a story keeps the
indicator honest — every rule should map back to something one side
or the other is doing.

### Act 1 — Demand wins the opening battle
A strong move up establishes a new high. Sellers get surprised and
supply exits at that level. **The top of this move becomes the
resistance.**

### Act 2 — Supply regroups
Price pulls back as profit-takers and short-sellers push in. The
pullback finds buyers somewhere above the prior breakout point. **That
low becomes the support floor.**

### Act 3 — War of attrition (the absorption)
Price oscillates between resistance and support for weeks or months.
Each rally attempt:
- Tests resistance (sellers defend)
- Is **shorter in duration** than the last
- Pulls back **less deeply** than the last
- Happens on **less volume** than the last

This is absorption: demand is quietly soaking up overhead supply. Both
sides slowly exhaust their ammunition.

### Act 4 — The exhaustion test (optional but common)
Often a final fake breakdown (the "spring" or "shakeout") takes out the
most recent higher low, triggering weak-hand stops. If buyers step in
immediately and price reclaims the range, supply is exhausted.

### Act 5 — Explosive breakout
Price clears resistance on volume expansion. Shorts cover. Prior
sellers who gave up buy back higher. No overhead resistance → move
accelerates.

**Time scale:** 2–5 months on the daily chart for liquid US equities;
1.5–3 years on weeklies.

---

## 2. Case study: SMCI, Jun 2023 – Jan 2024

`SMCI` NASDAQ, daily. Base window Aug 2023 – Jan 17 2024. Breakout
Jan 19 2024.

### The war, phase by phase

| Phase | Dates | Price | Volume | What happened |
|---|---|---|---|---|
| First battle won | May – Aug 7 2023 | $13 → $35.33 | Expanding | Pre-base rally. Sellers overwhelmed. **$35 = resistance**. |
| Regrouping | Aug 8 – Aug 20 2023 | $35 → $22 | High | Profit-taking, short-sellers push in. **$22 = support**. |
| War of attrition | Aug 2023 – Jan 10 2024 | $22 – $32 range | Steadily declining | 5+ months of oscillation. Each push to resistance shorter. Volume drying up. |
| Shakeout test | Jan 10 – Jan 17 2024 | Dip to mid-range, reclaim | Pop on reclaim | Sellers' last stand. Did not take out $22. Spring candle Jan 17. |
| Breakout | Jan 19 2024 | Gap through $35 | 3–4× avg | Absorption complete. |
| Post-breakout | Jan – Feb 2024 | $35 → $85 | Persistent | Unopposed trend. +140% in ~30 bars. |

### Candle-level observations

- **Upper wicks at resistance shrank over time** → sellers arrived
  late or weak. Each test of $35 showed less aggressive rejection.
- **Lower wicks at support shrank over time** → buyers didn't have to
  chase. They were waiting.
- **Jan 17 long-lower-wick green close** = textbook spring. That single
  candle said "sellers tried one more time and failed."
- **Volume on the final rally (late Dec – Jan 10) was the lowest of the
  entire base** — confirming absorption.

### What an outside observer could conclude

> "This stock is being accumulated quietly. Each time price touches $35
> someone sells, but not as many as before. Each time price touches
> $22 someone buys, and the buyers are winning. The first group that
> runs out of ammunition — sellers at $35, because the stock keeps not
> going down — loses the range. That happens around mid-January."

This narrative is what the indicator should detect.

---

## 3. Translating the narrative to indicator logic

| Narrative element | Code test |
|---|---|
| "Flat ceiling" (resistance) | Max of pivot highs in lookback; only pivots within `X × ATR` of that max count as touches |
| "Higher floor" | Each pivot low strictly higher than the prior (`requireHigherLows`) |
| "Each pullback shallower" | Final contraction depth ≤ `compressionMax × first depth`. Overall compression, not strict monotonic per step |
| "Volume drying up" | `SMA(vol,10) / SMA(vol,50)` ≤ `volDryupPct` at the apex |
| "Base is long enough" | `bar_index − first-cluster-pivot-bar` within `[minBase, maxBase]` |
| "Sellers surprised by rally" (Act 1) | `useStrength`: stock rallied ≥ `minRally` in `strengthBars`, currently within `pullbackCeiling` of that high |

### Deliberately NOT required

- **Minervini Trend Template** (`close > SMA50 > SMA150 > SMA200`, SMA200
  rising): absorption often forms right after a big move, before the
  MAs stack. OLECTRA failed this test while showing perfect absorption.
- **Strict per-step monotonic tightening**: real bases don't tighten
  smoothly. OLECTRA went 21.6% → 12% → 9% → 7% — two of the three
  step-ratios are 0.75–0.78, which fails a strict 0.6 rule.
- **ATR contraction as a separate test**: redundant with depth
  compression + volume dry-up. Kept off by default in v2.
- **Shakeout / spring as a requirement**: it's a CONFIRMATION signal,
  not a definition. Many valid absorptions break out without a visible
  spring. Plan to flag it when present (v3) but not require it.

---

## 4. Calibration log

### OLECTRA GREENTECH (NSE) — Feb – Aug 2023 — reference chart

| Parameter | Value | Notes |
|---|---|---|
| Base length | 104 bars (~5 months) | Longest case studied |
| First depth | 21.63% | Deep initial pullback after gap-up |
| Depths sequence | 21.63% → 12.03% → 9.07% → 7.05% | Per-step ratios: 0.556, 0.755, 0.778 |
| Overall compression | 7.05 / 21.63 = 0.326 | Passes at 0.5 default |
| Touch count at resistance | 4 (approx. ₹735) | All within ~1% of resistance |
| Volume signature | Declining with each pullback | User's reference image had volume arrows drawn |
| Outcome | Breakout to new all-time high | Multi-month run after breakout |

### SMCI (NASDAQ) — Aug 2023 – Jan 2024 — measured 2026-04-23

Investigated programmatically via `scripts/smoke_vcp_absorption.py
SMCI --check-date 2024-01-17`. The per-gate diagnostic dumps the
actual swing values and tests every threshold independently.

**Surprising finding: SMCI is not a strict flat-ceiling absorption.**

The "resistance" at $35.70 was a single spike high on Aug 7 2023.
The intervening swing highs (Aug – Dec 2023) ranged $28.77 – $32.91 —
that's **2.18 to 3.83 ATR below** the resistance:

| Date | Swing high | Distance from $35.70 |
|---|---|---|
| 2023-07-19 | $32.91 | 1.54 ATR |
| 2023-08-07 | $35.70 | 0.00 ATR (the spike) |
| 2023-08-24 | $29.83 | 3.24 ATR |
| 2023-09-11 | $28.77 | 3.83 ATR |
| 2023-10-10 | $31.75 | 2.18 ATR |
| 2023-11-20 | $30.59 | 2.83 ATR |
| 2023-11-29 | $30.65 | 2.79 ATR |
| 2023-12-18 | $32.76 | 1.63 ATR |

To call all these "touches at $35," `cluster_atr` would need to be
≥4.0 — at which point we'd accept basically any wide consolidation
as absorption, diluting the signal.

Volume **increased** during the base (last-30-bar avg / prior-60-bar
avg = 1.059), which is the opposite of dry-up. SMCI was a hot AI
stock with constant news flow, not quiet accumulation.

**Conclusion:** SMCI's structure is a **wide consolidation /
cup-with-handle**, not absorption-at-resistance. The user's narrative
was directionally right about the buyer/seller battle but the price
structure tells a different story than OLECTRA's. This is a Pattern
B (wide base) candidate; absorption (Pattern A) is OLECTRA / AVGO
2023 / FSLR 2023 / CROX 2007.

**Action item:** consider a separate `wide_base_breakout` detector for
Pattern B. Don't loosen absorption thresholds to swallow Pattern B —
that would lose the precision that makes Pattern A worth detecting.

### AVGO (NASDAQ) — May 2022 – Mar 2023 — measured 2026-04-23

Detector fires on **2023-02-28** at PQS 100. Diagnostic:

| Field | Value |
|---|---|
| Resistance | $58.88 |
| Touches | 3 (within 1.5 ATR) |
| Contractions | 3 |
| Depths sequence | 10.14% → 4.44% |
| Overall compression | 0.437 (≤ 0.50 threshold) |
| Volume ratio (base/pre) | 0.83 |
| Base length | 215 bars (~10 months) |
| Higher-lows violations | 0 |
| Entry / stop / TP2 | $58.88 / $50.89 / $69.84 |

AVGO went from $58.88 in Feb 2023 to ~$130 by year-end — a textbook
absorption breakout. The detector found it cleanly with default
calibration.

**This validates Pattern A detection.** AVGO is the new gold-standard
calibration target for absorption.

### Other candidates queued for measurement

- CROX daily Feb – Jul 2007 (IBD textbook) — needs download
- FSLR daily May – Jul 2023 (~$210 absorption) — needs download
- CELH daily Feb – Aug 2022 — needs download
- NFLX daily 2003 base — needs download (data quality caveat)

### Full-cache scan — 25 tickers × ~20 years — 2026-04-23

Ran `python -m scripts.smoke_vcp_absorption <25 tickers> --csv
detections.csv`. Result: **428 total detections across 22 tickers**
(zero on AMZN, BA, SMCI, WMT — SMCI correctly excluded as Pattern B,
others likely don't form strict absorption bases in the sample).

Top-PQS detection per ticker (top 10 shown here; full list in
`detections.csv` + the per-ticker summary was printed to stdout):

| Ticker | Date | Entry | Base | Compress | Vol | Touches |
|---|---|---|---|---|---|---|
| AVGO | 2021-06-21 | $44.46 | 77b | 0.26 | 0.78 | 6 |
| AAPL | 2007-04-25 | $2.94 | 72b | 0.39 | 0.66 | 3 |
| MSFT | 2020-06-16 | $180.66 | 87b | 0.27 | 0.61 | 3 |
| GOOGL | 2021-07-20 | $122.10 | 57b | 0.14 | 0.78 | 3 |
| TSLA | 2020-12-14 | $167.51 | 72b | 0.36 | 0.65 | 4 |
| NVDA | 2017-09-22 | $4.32 | 73b | 0.34 | 0.76 | 4 |
| V | 2024-12-03 | $289.86 | 177b | 0.45 | 0.78 | 3 |
| META | 2024-10-11 | $541.11 | 130b | 0.41 | 0.82 | 4 |
| ORCL | 2012-09-21 | $26.90 | 201b | 0.09 | 0.78 | 3 |
| DIS | 2011-01-11 | $32.69 | 176b | 0.15 | 0.76 | 4 |

**Known limitation: detection persists across bars.** AVGO 2021-06-21
is one entry in the table but the detector fires on 6+ consecutive
bars while the pattern holds (the "V had 22 detections Nov 6–Dec 6"
row cluster is another example). For production, add a debounce:
emit once per base, then suppress until price either breaks out
(entry hit), invalidates (stop hit), or the base structure changes.
Added to v3 plan.

---

## 5. Open research questions

- **Confluence from Form 4 / 13F:** does insider buying or 13F
  accumulation during the base window raise post-breakout success
  rate? Planned experiment once insider-transaction storage lands.
- **Explicit spring detection:** add a v3 pass that looks for a
  long-lower-wick green candle near the most recent higher low in the
  last N bars. Emit as a secondary confidence score, don't require.
- **Volume profile vs flat volume SMA:** `SMA(10)/SMA(50)` is a crude
  dry-up proxy. Better would be cumulative buy-vs-sell volume imbalance,
  but that needs tick data we don't have locally.
- **Multi-timeframe calibration:** weekly absorption takes 1.5–3 years.
  Default `minBase` / `maxBase` should scale with timeframe.
- **False-breakout filter:** track how often an apparent breakout fails
  within 5 bars (closes back inside the base). Aim for ≤ 20% failure
  rate in calibrated backtest.
- **Resistance level drift:** sometimes the ceiling slowly rises (mild
  ascending triangle). Current algo requires flat — should we support
  a small positive slope, and how do we define it?

---

## 6. Version history

- **v1** (2026-04-23): Initial Minervini-style VCP. Required Trend
  Template + strict monotonic tightening. Too strict for absorption
  patterns — rejected OLECTRA and SMCI.
- **v2** (2026-04-23): Rewritten for absorption specifically. Dropped
  Stage 2 default, added explicit resistance-level definition, added
  higher-lows test, overall compression replaces monotonic, added
  swing-pivot visualization for debugging.
- **Python port** (2026-04-23): `agents/detectors/vcp_absorption.py` +
  `scripts/smoke_vcp_absorption.py`. Per-gate diagnostic tool tests
  each threshold independently. Calibrated against AVGO Feb 2023
  (PQS 100 detection). Default changes from Pine v2:
  - `cluster_atr` 0.7 → 1.5 (AVGO touches span ~1 ATR naturally)
  - `max_final_depth` 0.12 → 0.18 (allow room for shakeout low)
  - `require_higher_lows` → `max_lowerlow_violations=1` (allow spring)
  - Volume measure: base-30 / pre-60 avg ratio (robust to single
    high-volume days) instead of SMA(10)/SMA(50) at latest bar
  - `vol_dryup_pct` 0.60 → 0.85 on the new smoothed measure
- **v3** (planned):
  - Detection debounce — emit once per base, not per bar
  - Explicit spring/shakeout detection as a confidence boost
  - Multi-timeframe default profiles (weekly vs daily)
  - Optional small positive slope for ascending-triangle variant
  - Sister detector `wide_base_breakout` for Pattern B (SMCI-style)

---

## 7. How to use this document

Every iteration of the Pine script should produce a row in section 4
(Calibration log) and, if new learnings, a paragraph in section 3
(Translating narrative to logic). When we port to Python, this doc
becomes the spec the detector must satisfy.

When in doubt about whether to tighten or loosen a parameter, re-read
section 1 (narrative) and ask: **is the change true to the story the
price is telling, or am I just fitting to one chart?**
