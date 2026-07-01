# 9JEmsSItdt4 — "LW Volatility Breakout / $1.1M" (TradingLab)

Source: <https://www.youtube.com/watch?v=9JEmsSItdt4> · ~8 min.

## Rules (mechanical)
- entry: Long when price touches/breaks the upper Donchian band AND the LWTI (Larry Williams Large Trade Index, period 25, smoothing 20) is green AND volume bar is above its 30-period MA and green. Short = mirror image on the lower band.
- exit/stop/target: Stop just below the Donchian midline (or recent swing low if the gap is large); take-profit at 2:1 R:R. Secret trick: skip entries near HTF support/resistance unless price is actively breaking that level.
- filters/params: Donchian length 96, LWTI(25, smooth 20), volume MA 30 — all explicitly tuned for the **5-minute** time frame.

## Verdict: ❌ REJECT — intraday-tuned + duplicate of deployed breakout
Author states all params (Donchian 96, LWTI 25, vol MA 30) are for the 5m chart and explicitly warns to re-test for other timeframes — we have no intraday data. The HTF-level "secret trick" reintroduces discretion. A daily-bar version (Donchian-N breakout + volume-above-MA + trend filter) collapses to our deployed Momentum Breakout (N-day-high + vol≥1.5x + ADX≥20 regime gate, PF 2.34) — Donchian-upper-band breakout IS an N-day-high breakout. No novel daily edge.
Status: rejected, not deployed
