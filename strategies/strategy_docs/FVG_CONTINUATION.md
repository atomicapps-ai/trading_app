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
