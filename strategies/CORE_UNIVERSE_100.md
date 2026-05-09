# core_universe_100 — Universe Snapshot

Generated: 2026-05-09T19:27:25.392887+00:00

## Funnel

- Stage 1 (Finviz): **123** tickers
- Stage 2 (local ATR% + SMA verify): **44** tickers
- Rejected: **79** (see below)

## Stage 1 filters

| Filter | Value | Meaning |
|---|---|---|
| `sh_price` | `o15` | Price > $15 |
| `sh_avgvol` | `o2000` | ADV > 2M |
| `cap` | `mid` | Mid+ market cap (~$2B+) |
| `geo` | `usa` | US-listed |
| `fa_pe` | `profitable` | Positive earnings |
| `fa_eps5years` | `pos` | 5-yr EPS growth positive |
| `fa_opermargin` | `pos` | Operating margin positive |
| `fa_curratio` | `o1` | Current ratio > 1 |
| `fa_debteq` | `u1` | Debt/Equity < 1 |
| `ta_sma50_pa` | `pa` | Price above SMA50 |
| `ta_sma200_pa` | `pa` | Price above SMA200 |

## Stage 2 filters (local)

- ATR(14) / close ∈ [1.5%, 5.0%]
- Re-verify: close > SMA50 AND close > SMA200

## Final universe (44 symbols)

| Symbol | Close | ATR% | dist >SMA50 | dist >SMA200 |
|---|---:|---:|---:|---:|
| AMD | $455.19 | 5.0% | +78.8% | +109.4% |
| TDC | $31.59 | 4.9% | +16.2% | +21.4% |
| FLEX | $142.17 | 4.5% | +84.6% | +122.1% |
| LRCX | $294.05 | 4.4% | +22.0% | +64.7% |
| BF-B | $27.68 | 4.4% | +4.8% | +0.4% |
| HOG | $25.42 | 4.2% | +21.4% | +9.3% |
| FCX | $61.65 | 4.2% | +0.7% | +21.2% |
| NEM | $116.51 | 4.1% | +3.8% | +20.4% |
| ESI | $43.90 | 4.0% | +21.2% | +50.9% |
| FTNT | $114.07 | 4.0% | +35.8% | +37.5% |
| AMAT | $435.44 | 3.9% | +16.7% | +58.6% |
| GTES | $26.09 | 3.9% | +7.0% | +7.9% |
| XYZ | $74.85 | 3.8% | +15.1% | +9.9% |
| ZM | $109.21 | 3.6% | +28.9% | +30.4% |
| TSLA | $428.35 | 3.5% | +11.8% | +5.9% |
| AVGO | $430.00 | 3.4% | +19.9% | +25.5% |
| HWM | $270.56 | 3.4% | +10.1% | +27.8% |
| EXEL | $48.16 | 3.4% | +10.7% | +15.4% |
| PPG | $109.61 | 3.4% | +1.6% | +2.6% |
| CDNS | $362.70 | 3.2% | +19.3% | +12.4% |
| LLY | $948.45 | 3.2% | +0.7% | +3.7% |
| NVDA | $215.20 | 3.1% | +14.1% | +16.5% |
| MNST | $86.29 | 2.9% | +13.5% | +19.2% |
| AHR | $51.71 | 2.7% | +3.6% | +12.1% |
| ADI | $416.52 | 2.7% | +19.6% | +46.5% |
| AMZN | $272.68 | 2.6% | +17.9% | +19.3% |
| GS | $936.48 | 2.5% | +7.5% | +12.7% |
| CTVA | $81.13 | 2.5% | +0.5% | +13.2% |
| FOXA | $62.94 | 2.4% | +4.0% | +0.6% |
| BAC | $51.31 | 2.4% | +1.6% | +0.3% |
| UNH | $379.98 | 2.4% | +22.7% | +20.9% |
| GOOGL | $400.80 | 2.4% | +23.8% | +40.1% |
| CTRE | $41.60 | 2.3% | +7.3% | +15.8% |
| GOOG | $397.05 | 2.3% | +23.3% | +38.8% |
| AAPL | $293.32 | 2.3% | +11.6% | +14.2% |
| DLR | $195.31 | 2.2% | +4.5% | +14.9% |
| OHI | $47.19 | 2.0% | +3.2% | +10.9% |
| AFL | $113.10 | 1.9% | +1.5% | +3.7% |
| AMH | $32.03 | 1.9% | +8.1% | +2.1% |
| ROST | $225.81 | 1.9% | +3.5% | +26.1% |
| WMT | $130.43 | 1.9% | +3.6% | +15.7% |
| COST | $1008.79 | 1.8% | +1.1% | +6.2% |
| BNL | $19.86 | 1.8% | +3.1% | +10.8% |
| KO | $78.42 | 1.7% | +2.0% | +9.7% |

## Rejected (79)

First 30 rejection reasons:

| Symbol | Reason |
|---|---|
| A | P below SMA50 or SMA200 (Finviz stale or just crossed under) |
| ABT | P below SMA50 or SMA200 (Finviz stale or just crossed under) |
| ADP | P below SMA50 or SMA200 (Finviz stale or just crossed under) |
| AJG | P below SMA50 or SMA200 (Finviz stale or just crossed under) |
| AMKR | ATR%=5.742% (need 1.5%-5.0%) |
| ANET | ATR%=5.739% (need 1.5%-5.0%) |
| BRK-B | ATR%=1.369% (need 1.5%-5.0%) |
| BRO | P below SMA50 or SMA200 (Finviz stale or just crossed under) |
| CDE | ATR%=6.338% (need 1.5%-5.0%) |
| CEG | P below SMA50 or SMA200 (Finviz stale or just crossed under) |
| CF | ATR%=5.241% (need 1.5%-5.0%) |
| CHRW | P below SMA50 or SMA200 (Finviz stale or just crossed under) |
| CME | P below SMA50 or SMA200 (Finviz stale or just crossed under) |
| COHR | ATR%=6.986% (need 1.5%-5.0%) |
| COIN | ATR%=5.801% (need 1.5%-5.0%) |
| COO | P below SMA50 or SMA200 (Finviz stale or just crossed under) |
| CPRT | P below SMA50 or SMA200 (Finviz stale or just crossed under) |
| CRH | P below SMA50 or SMA200 (Finviz stale or just crossed under) |
| CTAS | P below SMA50 or SMA200 (Finviz stale or just crossed under) |
| CTRA | P below SMA50 or SMA200 (Finviz stale or just crossed under) |
| CTSH | P below SMA50 or SMA200 (Finviz stale or just crossed under) |
| DHI | P below SMA50 or SMA200 (Finviz stale or just crossed under) |
| DHR | P below SMA50 or SMA200 (Finviz stale or just crossed under) |
| DOCS | P below SMA50 or SMA200 (Finviz stale or just crossed under) |
| DXCM | P below SMA50 or SMA200 (Finviz stale or just crossed under) |
| EA | ATR%=0.453% (need 1.5%-5.0%) |
| ELF | ATR%=5.152% (need 1.5%-5.0%) |
| ENPH | ATR%=6.298% (need 1.5%-5.0%) |
| EPRT | P below SMA50 or SMA200 (Finviz stale or just crossed under) |
| EW | P below SMA50 or SMA200 (Finviz stale or just crossed under) |
| ... | (and 49 more) |