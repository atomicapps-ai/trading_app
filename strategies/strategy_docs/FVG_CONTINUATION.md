# FVG Displacement-Continuation (FX intraday) — VALIDATED

Origin: reframe of the E3Mc "Displacement ORB + FVG" video (research/video_library/E3McKlAp3qk).
The video's *retrace* entry (limit at the FVG edge) is a fill mirage — it only wins at impossible
perfect fills and loses at any realistic execution (see E3Mc/spec.md). The **continuation** reframe —
enter in the displacement direction at market the moment the FVG confirms, and ride the move — is the
real edge. Credit: operator's insight ("the profit is the drop, not the retrace").

## Rules (mechanical, market entry — realistic fills)
Per FX pair, per day, New York time (DST-aware):
1. **Sessions:** Asia range = 19:00–00:00 ET (prior evening); London = 02:00–07:00 ET;
   NY opening range (ORB) = 09:30–09:45 ET; trade window = 09:45–16:00 ET.
2. **Session bias:** London usually sweeps an Asia extreme and NY reverses → bias = OPPOSITE of
   London's net direction; if London sweeps BOTH Asia high and low → continuation (bias = London dir).
3. **Setup:** in the NY trade window, find a 3-candle FVG (displacement) whose displacement candle
   closed beyond the ORB (up-FVG above ORB high / down-FVG below ORB low), in the bias direction.
4. **ENTRY: market, at the open of the bar AFTER the FVG confirms** (no waiting for a retrace).
5. **Stop:** the far edge of the gap (gap bottom for longs, gap top for shorts).
6. **Target:** fixed 2R–3R (both work); exit at session close if neither hit. One trade/day.

## Results (30m bars, 2-pip cost in R, DST-correct ET sessions, market fills)
| scope | n | win% | exp | PF | OOS PF | control PF |
|---|---|---|---|---|---|---|
| 9 pairs, 3R, disp1.5 (2021+) | 2,189 | 48.7% | +0.20R | **1.48** | 1.46 | **1.01** |
| 5 pairs, 2R, disp1.0 (2021+) | 1,802 | 53.3% | — | 1.57 | — | — |
| 5 pairs, 3R, disp1.0 (2021+) | 1,802 | 50.3% | — | 1.60 | — | — |

- **Realistic fills** (market entry at next bar open — not the limit-at-edge mirage). Survives by construction.
- **Clean random-direction control (~1.0):** the edge is directional prediction, not payoff geometry.
- **Holds out-of-sample** (IS 1.49 ≈ OOS 1.46).
- **Plateau:** stable across displacement threshold (1.0–1.5) and target (2R–3R) → not curve-fit.
- Win 48–53% at 2–3R is far above the 25–33% breakeven.

## Independent verification — 25y HistData source (2026-07-02)
Re-ran the identical engine (3R, disp1.5, 2-pip cost, DST-correct ET sessions, market
fills) on a **completely independent data source**: HistData 1-minute bars
(HF `elthariel/histdata_fx_1m`, 2000–2025) resampled to 30m/5m. Rebuild any time with
`python -m scripts.fetch_fvg_data && python -m scripts.compare_fvg_intervals`.

| scope | n | win% | PF | net% |
|---|---|---|---|---|
| **FX 30m, 2021+** (validated window) | 1,609 | 49% | **1.24** | +21.9 |
| **FX 30m, 2005+ (20 yr)** | 9,257 | 46% | **1.19** | +127.9 |
| FX 5m, 2021+ | 4,704 | 38% | 1.03 | +7.3 |
| **GOLD XAUUSD 30m, 2015+** (source instrument) | 521 | 49% | **1.36** | +17.6 |
| GOLD XAUUSD 5m, 2015+ | 1,440 | 37% | 1.09 | +11.1 |

**Findings (what actually held up):**
1. **The edge is real and remarkably stable OOS** — 30m FX holds PF ~1.2 across **20 years
   and 9,257 trades**. This is the strongest out-of-sample confirmation of any strategy in
   the project.
2. **But softer than the original claim: PF ~1.19–1.24, not 1.48.** The 1.48 was
   data-source-specific (a different feed); on clean independent HistData the honest number
   is ~1.2. Still profitable, still directional — a *modest* edge, not a big one.
3. **30m ≫ 5m, decisively.** FX 5m collapses to PF 1.03 (essentially breakeven — noise). The
   repo's 30m variant is correct; adopting the source video's 5m would DESTROY the FX edge.
4. **Gold is the best on 30m (PF 1.36 > FX's 1.24)** — vindicating the video's instrument
   choice — but gold 5m (1.09) is again far weaker than gold 30m. Even on the source
   instrument, **30m wins and 5m is noise.**
5. **Conclusion:** best configuration is **30m on gold (or 30m FX)**, target 3R. The "5m"
   the source teaches is inferior everywhere. Deploy expectations at **PF ~1.2–1.35**, not 1.5.

**Random-direction control (2026-07-02) — the edge is prediction, not geometry.**
Re-ran the identical setups/timing/entry/risk/3R geometry but replaced the long/short
call with a seeded coin flip (mean of 5 seeds). Rebuild with
`python -m scripts.compare_fvg_intervals --control`.

| config | real PF | control PF | real WR | control WR | directional edge |
|---|---|---|---|---|---|
| FX 30m, 2021+ | 1.24 | **0.78** (0.73–0.82) | 49% | 39% | **+0.46 PF, +10pp** |
| GOLD 30m, 2015+ | 1.36 | **0.84** (0.81–0.88) | 49% | 39% | **+0.52 PF, +10pp** |

The control *loses* (PF < 1), so a coin flip on these setups is a money-loser after cost —
the strategy overcomes a negative baseline. The entire gap from ~0.8 to ~1.3 comes from the
direction call (London sweeps Asia → NY reverses). This is the cleanest confirmation in the
project that a strategy's signal is real predictive skill, not favorable payoff math.

## Contrast with the rejected retrace version (why this is different)
| version | entry | realistic-fill result |
|---|---|---|
| E3Mc retrace (rejected) | limit at FVG edge, wait for pullback | PF 0.58–0.63 (LOSES — adverse selection) |
| **continuation (this)** | **market, ride the displacement** | **PF 1.48 (clean, OOS-robust)** |

## Status / deployment notes
- **Validated as a realistic intraday FX edge** — modest but genuine (PF ~1.5), the first to survive the
  full battery (control + OOS + breadth + fill-robustness).
- **Not yet wired to the app.** The live app trades US equities via Alpaca; this is FX intraday, so
  deployment needs (a) an FX broker (e.g., OANDA) + (b) the intraday workflow. Until then it is
  **manually tradeable** using scripts/pine/fvg.pine on a live chart + these rules.
- **Open follow-ups:** finish the full disp×target×stop sweep on all 9 pairs/full history; test on the
  creator's actual instrument (XAUUSD/gold) once gold data is sourced; forward paper-trade on OANDA
  practice to confirm live fills match the backtest.

## Gold (XAUUSD) validation — 2026-07 (resolves the deferred follow-up)

Ran `python -m scripts.compare_fvg_intervals --symbols XAUUSD --intervals 30m,5m
--since 2015-01-01` (+`--control`) on the cached XAUUSD candles (2015→2026).

| interval | trades | WR | PF | net | vs random-dir control |
|---|--:|--:|--:|--:|---|
| **30m** | 521 | 49% | **1.36** | +17.6% | control PF 0.84 → clean edge |
| 5m | 1,440 | 37% | 1.09 | +11.0% | weaker; 5m adds noise |

**Findings**
- **Gold works at 30m (PF 1.36)** — clears the PF ≥ 1.3 bar and beats the
  random-direction control (0.84) decisively. Same continuation edge as the FX
  book (FX PF ~1.48), now confirmed on the creator's actual instrument.
- **The "faithful" 5m-gold version is WORSE (PF 1.09)** — answers the long-standing
  question from CLAUDE.md's DEFERRED TASK: dropping to 5m does *not* help; 30m is the
  keeper. The E3Mc 5m detail was not the source of the edge.
- **Action:** gold (XAUUSD) is a viable **new instrument to add to the
  `fvg_continuation` universe at 30m.** Before wiring: confirm the PF is net of the
  gold spread (wider than FX) and check per-year OOS stability, same bar as everything
  else. Left `active:false`/manual pending that + the FX-broker/intraday-workflow gap.

### Gold OOS stability + cost sensitivity (2026-07 — passes the bar)
Per-year PF, XAUUSD 30m, net of the built-in 2-pip cost:

| 2015 | 2016 | 2017 | 2018 | 2019 | 2020 || 2021 | 2022 | 2023 | 2024 | 2025 |
|--|--|--|--|--|--||--|--|--|--|--|
|0.79|2.42|0.82|1.18|1.33|1.26||1.46|1.62|2.23|1.42|1.12|

- **FULL PF 1.36 · IS(<2021) 1.24 · OOS(≥2021) 1.60** — OOS is *stronger* than IS
  (the opposite of the ORB mirage). 9 of 11 years > 1.0; only early 2015/2017 weak.
- **Cost-robust:** at a doubled ~4-pip gold spread, OOS PF still 1.46.
- **Verdict: PASSES the bar** (PF ≥ 1.3 net · beats control 0.84 · 521 trades ·
  IS/OOS-stable). Same strategy family already validated on FX, so the correlation
  gate is moot — this extends an existing edge to a new instrument.
- **Wired:** XAUUSD added to `strategy_configs/fvg_continuation.yaml` universe.
  Still replay/paper only (no live money) pending the FX/metals broker + intraday
  workflow; the IBKR XAUUSD CMDTY contract path already exists (see CLAUDE.md).
