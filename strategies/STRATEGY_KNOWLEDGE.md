# Strategy Knowledge Base

Living document. Each external strategy you stage in `strategies/external/`
gets analyzed and summarized here. Over time this becomes the playbook
for what works, what doesn't, and what primitives are worth reusing.

**Last updated:** 2026-05-08

---

## Validated truths so far

(Things that come from our own data, not claims from sources.)

| Finding | Evidence | Confidence |
|---|---|---|
| DL real WR is **53%, not 82%**. Pattern-matching on opening candles alone has a thin edge | 4-yr replay, n=103 trades, PF 1.21 | High |
| **Per-symbol parameter optimization is essential.** TSLA's optimal SuperTrend is `atr_mult=2.5, atr_period=7`; SPY's is `atr_mult=4.0, atr_period=21` — opposite ends of the grid | 11,760-combo daily sweep, May 2026 | High |
| **PMax beats SuperTrend universally** when properly tuned (16/16 symbols PF>1 vs SuperTrend's 16/16 but lower median PF 1.40 vs PMax 2.16) | Same sweep | High |
| **Author default params from TradingView Pines are usually wrong.** ChartArt's default `bb_length=200` loses on 16/16 symbols; `bb_length=20` makes Bollinger+RSI a top performer on 5/16. ChartArt's `very_slow_length=200` for MACD loses; `100` wins on 6/11 | Same sweep | High |
| **MACD+SMA200 has a high-PF / low-WR signature** that's consistent across 11 symbols (median WR 12.8%, median PF 5.58). It captures rare big trends and pays for it with many small losses | Same sweep | High |
| **Bollinger+RSI works on defensive/index names only** (SPY/IWM/XLF/HD/BA), NOT on growth/tech | Same sweep | Medium-high |
| **PMax wins on tech/momentum** (NVDA/MSFT/AMD/META/INTC/AMZN/TSLA/GS) | Same sweep | High |
| Continuation > reversal in opening 15m | scan_opening_patterns.py (n=large) | High |
| 30m candles encode better signal than 15m | same source | Medium |
| Conviction filtering (body % + close-in-range + volume) tightens signal materially | same source | Medium |
| Catastrophic-stop-only exits leak edge — bar-relative stops likely better | DL replay shows MAE > 1.4% on winning days | Medium |
| VIX≥20 regime gate filters out enough days to keep noise low | 1090 days → 103 trades = ~10% selectivity | Medium |
| **ATR-based bands are the universal primitive** — appear in 18/48 winners across all strategies | Optimizer primitive frequency | High |
| **Volume-as-filter is absent from all 4 external strategies.** DL is the only strategy that uses volume at all in this codebase | Static analysis of all 5 Pines | High |

---

## Indicator primitives in use across strategies

(Build a vocabulary so we can reuse what works.)

### Conviction primitives (per-candle)
- **Body strength** = `|close - open| / (high - low)`. Threshold typically ≥ 0.5
- **Close-in-range / buy pressure** = `(close - low) / (high - low)`. ≥ 0.6 for bullish, ≤ 0.4 for bearish
- **Volume vs slot-median** = current 30m volume / rolling 20-day median for that exact slot. Threshold typically ≥ 1.3-1.5

### Regime primitives (daily-context)
- **VIX prior-session close** — gates "vol-on" days
- **Gap % vs prior close** — filters for overnight catalysts
- **Price vs 20/50/200 SMA** — trend regime
- **ADX(14)** — trending vs ranging (DL caps at ≤35 = avoiding strong trends, surprising)
- **RSI(14)** range filter — gates against extreme overbought/oversold

### Microstructure primitives (intraday)
- **VWAP reclaim/reject** — close one side then the other
- **Opening range breakout** — first 30m high/low as triggers
- **NR7 / inside bar** — compression preceding expansion
- **Squeeze** (Bollinger inside Keltner) — vol-of-vol collapse before breakout

### Exit primitives
- **Time-stop at 15:00 ET** — DL's exit (avoids close illiquidity)
- **Catastrophic % stop** — DL uses 3% (too wide; soaks losers)
- **Bar-relative stop** — opposite end of trigger bar (typical 0.3-0.8%)
- **R-multiple targets** — 1R, 1.5R, 2R legs (vs flat % targets)
- **Trail to break-even** at +0.5R or +1R — locks in stop-out protection

---

## External strategies analyzed

Each entry below was extracted from the staged `.pine` source. The "Per-symbol
sweep grid" section under each is the parameter space the optimizer will search
when tuning that strategy for each of the bellwether-16 symbols.

---

### 1. `bollinger_rsi_chartart` — RSI + Bollinger Bands double trigger
**Source:** [strategies/external/bollinger_rsi_chartart/source.pine](strategies/external/bollinger_rsi_chartart/source.pine)
**Author:** ChartArt (TradingView), v1.1, Jan 2015
**Family:** Mean reversion · **Author timeframe:** unspecified

**What it does (plain English):**
Trades the simultaneous extreme of RSI *and* price on Bollinger Bands.
- **Long** when RSI crosses above 50 (`oversold` is set to 50, not the textbook 30) AND close crosses up through the lower BB at the same bar
- **Short** when RSI crosses below 50 AND close crosses down through the upper BB
- Stop is the band itself (`stop=BBlower` for longs, `stop=BBupper` for shorts) — bar-relative, NOT percent-based
- Has no take-profit; relies on next signal to reverse

**Parameters:**
| Name | Default | Author range | Sweep range (proposed) | Reasoning for sweep |
|---|---:|---|---|---|
| `RSIlength` | 6 | unspecified | [4, 6, 8, 10, 14, 20] | Default 6 is unusually short — author probably meant fast mean-rev; classic RSI is 14. Sweep covers both cultures |
| `BBlength` | 200 | minval=1 | [20, 50, 100, 200] | 200 = very slow regime context (~10 mo of 30m bars); 20 = Bollinger classic. Different symbols will favor different regimes |
| `BBmult` | 2.0 (hardcoded) | originally 2.0, range 0.001-50 commented out | [1.5, 2.0, 2.5, 3.0] | Mult drives band width = entry frequency. AAPL/MSFT may need wider bands than IWM |

**Critique:**
- RSI thresholds at 50 (not 30/70) make this a *trend reversal* strategy, not a true mean-rev. Both indicators must "wake up" on the same bar — that's a strong filter and explains why sample will be sparse
- No TP = relies on opposite signal to exit. Could ride a winner indefinitely OR get steamrolled. Probably needs an added exit rule (time-stop or % from entry) for honest backtesting
- v=2 Pine, no overlap protection — if a bar has both signals it could double-flip
- **Repaint risk:** uses `crossover` on close, no `request.security` — appears safe

**Primitives used:** RSI(N) reversal · Bollinger(N, K) extreme · simultaneous-trigger filter

---

### 2. `macd_sma200_chartart` — MACD + SMA200 trend filter
**Source:** [strategies/external/macd_sma200_chartart/source.pine](strategies/external/macd_sma200_chartart/source.pine)
**Author:** ChartArt (TradingView), v1.0, Nov 2015
**Family:** Trend-following · **Author timeframe:** unspecified, likely daily

**What it does (plain English):**
Classic "MACD + 200 SMA regime gate" structure with stacked confirmations.
- **Long** when ALL true: MACD histogram crosses up through 0, MACD line > 0, fastMA > slowMA, AND `close[slowLength]` (i.e., 26 bars ago) was above the 200 SMA
- **Short** is the mirror condition
- Entry uses a `stop` order at the bar's low (for long) or high (for short) — **stop-entry, not market**, so the next bar must trigger
- Has `strategy.cancel` on regime flip (slowMA crosses very-slow MA the wrong way)
- Built-in `max_intraday_loss(50%)` killswitch

**Parameters:**
| Name | Default | Range | Sweep range | Reasoning |
|---|---:|---|---|---|
| `fastLength` | 12 | minval=1 | [8, 12, 21] | Standard MACD = 12; faster (8) for choppier names; 21 = Elder/Vegas variant |
| `slowLength` | 26 | minval=1 | [21, 26, 34, 50] | Standard 26; longer for less whip on TSLA-style names |
| `signalLength` | 9 | minval=1 | [6, 9, 14] | Faster signal = earlier entry but more whips |
| `veryslowLength` | 200 | minval=1 | [100, 150, 200, 300] | The regime filter. Shorter = more trades; 200 is canonical |
| `maxIdLossPcnt` | 50 | unbounded | leave fixed | Safety, not optimization target |

**Critique:**
- "Stacked confirmation" pattern is robust — 3 things must agree before entering. Means few trades but probably good quality
- Stop-entry adds 1 bar of latency; on 30m that's 30 minutes of slippage potential. May lose edge on fast moves
- No TP, exit via opposite signal only. **Combined with stop-entry that means the avg trade duration could be huge** — important for capital efficiency comparison
- Uses `close[slowLength]` (26 bars ago) for SMA200 filter — that's a curious choice, looks like a coding artifact. Could be a bug; worth verifying behavior matches author intent
- **Repaint risk:** No `request.security`, but `strategy.cancel` mid-bar may behave oddly in backtest vs live

**Primitives used:** MACD line/signal/histogram · SMA(very-slow) regime filter · stop-entry · regime-flip cancellation

---

### 3. `pmax_explorer` — Profit Max trailing band (multi-symbol scanner version)
**Source:** [strategies/external/pmax_explorer/source.pine](strategies/external/pmax_explorer/source.pine)
**Author:** KivancOzbilgic (TradingView)
**Family:** Trend-following (volatility-trailed) · **Author timeframe:** any

**What it does (plain English):**
Variant of SuperTrend where the ATR band trails a moving average instead of price.
- Compute `MAvg` over chosen length (8 MA types selectable: SMA/EMA/WMA/TMA/VAR/WWMA/ZLEMA/TSF)
- Compute `longStop = MAvg - Mult*ATR` and `shortStop = MAvg + Mult*ATR`, ratcheted (only moves in trend direction)
- **Long** when `MAvg` crosses up through `PMax` (band line); **Short** on cross down
- Uses `strategy.entry("Long"/"Short")` on each cross — auto-flips position
- Has a multi-symbol scanner (lines 146-307) that lists "Confirmed Reversals" for 20 symbols across multiple TFs — IGNORE for our purposes; we feed one symbol at a time

**Parameters:**
| Name | Default | Range | Sweep range | Reasoning |
|---|---:|---|---|---|
| `Periods` (ATR) | 10 | int | [7, 10, 14, 21] | ATR(14) is canonical; 10 is faster; 7 nimble |
| `Multiplier` | 3.0 | step=0.1 | [2.0, 2.5, 3.0, 4.0] | Wider mult = fewer flips. 3.0 default is fairly aggressive |
| `length` (MA) | 10 | minval=1 | [8, 10, 14, 21] | MA period. Mostly determines responsiveness |
| `mav` (MA type) | EMA | enum 8 options | ["EMA", "SMA", "WMA"] | 8 types is too many to sweep — restrict to most popular 3. Could expand on stage 2 |
| `changeATR` | true | bool | leave fixed (true) | true = real ATR, false = SMA-of-true-range. Author default works |

**Critique:**
- Effectively SuperTrend with an MA layer between price and the band — should reduce false flips on choppy bars but adds lag
- Auto-flip means strategy is always in the market — may not be desired (we'd want regime filter)
- **CRITICAL:** the Pine `Pmax(M, P)` function defined inline uses a **different** computation than the inline `longStop`/`shortStop` lines above. The strategy fires off `buySignalk` from the top calculation, which is the simpler form. The function is only used by the multi-symbol scanner. Translation must use the top form
- Multi-symbol scanner (the bulk of the file, lines 146-325) is presentation-only and irrelevant to the trade logic
- **Repaint risk:** ratcheted stops + ATR — none of the usual repaint sources present

**Primitives used:** ATR-trailed band · MA(N) of multiple types · ratcheted stop · cross-of-MA-and-band as trigger

---

### 4. `supertrend_kivanc` — Classic SuperTrend
**Source:** [strategies/external/supertrend_kivanc/source.pine](strategies/external/supertrend_kivanc/source.pine)
**Author:** KivancOzbilgic (TradingView)
**Family:** Trend-following (volatility-trailed) · **Author timeframe:** any

**What it does (plain English):**
Vanilla SuperTrend. ATR band trails *price* (specifically `hl2`).
- `up = src - Mult*ATR` (ratcheted up while close > prev up)
- `dn = src + Mult*ATR` (ratcheted down while close < prev dn)
- `trend` flips between +1 / -1 when close crosses opposite band
- **Long** on flip from -1 to +1; **Short** on flip from +1 to -1
- Has date-window filter (FromMonth/Year, ToMonth/Year) — ignore in our framework; we slice by date externally

**Parameters:**
| Name | Default | Range | Sweep range | Reasoning |
|---|---:|---|---|---|
| `Periods` (ATR) | 10 | int | [7, 10, 14, 21] | Classic ATR(14); 10 is the SuperTrend default |
| `Multiplier` | 3.0 | step=0.1 | [1.5, 2.0, 2.5, 3.0, 4.0] | Lower = more flips/whipsaw; higher = patient. Probably the dominant param |
| `src` | hl2 | hl2/close/hlc3 | leave fixed (hl2) | Author canonical; not worth sweeping |
| `changeATR` | true | bool | leave fixed (true) | Same as PMax |

**Critique:**
- The benchmark trend-follower. If our DL beats this, that's a real signal we have edge. If it doesn't — DL probably isn't worth running
- 100% in-market again — needs a flat-state regime filter for honest comparison
- Probably the cleanest Pine in the batch — minimal cruft, no scanner overhead
- **Repaint risk:** None obvious

**Primitives used:** ATR(N)-trailed price band · ratcheted stop · trend-flip as signal

---

### 5. `empirical_breakout_v1` — Score-gated breakout (your own — already in Python)
**Source:** [strategies/external/empirical_breakout_v1/source.pine](strategies/external/empirical_breakout_v1/source.pine) (Pine version)
**Existing Python:** `agents/detectors/breakout_empirical.py`
**Family:** Trend-following / breakout · **Author timeframe:** daily (the spec uses 60d/180d/252d windows)

**What it does (plain English):**
Multi-gate breakout detector with a continuous score on top.
- **Hard gates** (all required, defaults from `data/threshold_spec.md`):
  - `pct_of_60d_high ≥ 0.98` (within 2% of 60-day high)
  - `close/sma50 ≥ 1.053` (5%+ above 50 SMA)
  - `RSI(14) in [59.17, 71.74]` (healthy momentum, not blowoff)
  - `max_dd_base ≤ 0.247` (base drawdown < 24.7%)
  - `base_len_25pct ∈ [12, 180]` (12-180 bars since last 25% pullback)
  - `n_contraction_pairs ≥ 5` (some swing structure)
- **Score** (0-100, weighted percentile-style on 10 features). Must be ≥ `min_score=50`
- **Trade plan:** entry at signal close · stop = base_low - 0.5×ATR (capped -10%) · TP1 = entry+2R (close half) · TP2 = entry+4R · time stop 120 bars

**Parameters (the "gates" double as tunable thresholds):**
| Name | Default | Range | Sweep range | Reasoning |
|---|---:|---|---|---|
| `gate_pct_60d_high` | 0.98 | [0.5, 1.0] | [0.92, 0.95, 0.98, 1.00] | Tighter = fewer signals; loosen on volatile names |
| `gate_close_vs_sma50` | 1.053 | [0.9, 1.5] | [1.02, 1.05, 1.10, 1.15] | Trend strength threshold |
| `gate_rsi_min` | 59.17 | [30, 90] | [50, 55, 60] | Lower bound of "healthy momentum" window |
| `gate_rsi_max` | 71.74 | [30, 90] | [70, 75, 80] | Upper bound (avoid blowoff tops) |
| `gate_max_dd_base` | 0.247 | [0.05, 0.5] | [0.15, 0.25, 0.35] | Tighter base = cleaner setup but rarer |
| `min_score` | 50.0 | [0, 100] | [40, 50, 60, 70] | Quality vs quantity trade-off |
| `stop_atr_buffer` | 0.5 | [0, 3] | [0.3, 0.5, 1.0] | How far below base_low to place stop |
| `tp1_r_multiple` | 2.0 | [0.5, 10] | [1.5, 2.0, 3.0] | When to take partial |
| `tp2_r_multiple` | 4.0 | [0.5, 20] | [3.0, 4.0, 6.0] | When to close remainder |
| `time_stop_bars` | 120 | [10, 365] | [60, 120, 180] | How long to hold a non-mover |

**Critique:**
- Already statistically derived — defaults are P10/P90 of 502 winning breakouts. That's a much better starting point than guessed thresholds in the other 4 Pines
- Designed for **daily** bars; using on 30m would need re-derivation of the percentiles. The Python version operates on dailies — appropriate
- This is the strategy worth tuning **per symbol** the most — different stocks have different "healthy momentum" zones (TSLA's RSI 75 might be normal; KO's might be a sell signal)
- Score function is symmetric around feature medians (penalty when extreme low OR high) — good design
- Long-only by construction — can't short. Halves the testable trade count

**Primitives used:** percentile-of-N-day high · close-vs-MA · RSI(14) range · base drawdown · contraction-pair counting · ATR-buffered stop · multi-leg R-multiple TP · time stop

---

## Cross-strategy primitive frequency (so far, before optimization)

(How often each primitive shows up across the 5 strategies. Primitives in 3+
strategies are "consensus" tools — strong candidates for the composite. Single-use
primitives are differentiators.)

| Primitive | bol_rsi | macd_sma | pmax | supertrend | emp_breakout | Count |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| RSI(N) | ✅ | | | | ✅ | 2 |
| MA / SMA / EMA | ✅ | ✅ | ✅ | ✅ | ✅ | 5 |
| Bollinger Bands | ✅ | | | | | 1 |
| MACD | | ✅ | | | | 1 |
| ATR | | | ✅ | ✅ | ✅ | 3 |
| ATR-trailed band (ratcheted) | | | ✅ | ✅ | | 2 |
| Long-MA regime filter | | ✅ | | | ✅ | 2 |
| Bar-relative stop | ✅ | ✅ | (band) | (band) | ✅ | 5 (all!) |
| TP / R-multiple targets | | | | | ✅ | 1 |
| Time stop | | | | | ✅ | 1 |
| Long-MA regime filter | | ✅ | | | ✅ | 2 |
| Repaint potential | low | low-med | low | low | low | — |

**Observations:**
- **All 5** use a moving average and a bar-relative stop — these are the truly universal primitives
- **ATR-driven stops** are common (3/5) — likely a real edge ingredient
- **Empirical Breakout is the only one with TP targets and time stops** — the others rely on signal reversal. This is a structural advantage for capital efficiency
- **RSI shows up only twice** but in completely different roles (mean-rev trigger vs. range gate) — the same primitive doing different jobs
- **No strategy has a volume primitive!** The DL detector's slot-volume-median check is the only volume filter in the whole stable. Worth testing whether adding volume filter to any of these 4 improves them

---

## Updated proposals (now that 5 strategies are characterized)

### Proposal 002: ATR-band trend with TP/time-stop overlay
**Status:** unbacktested · **Source:** synthesized 2026-05-08

Take SuperTrend's ATR-trailed band entry signal, but instead of staying in market
forever, apply Empirical Breakout's exit framework:
- Entry: SuperTrend long flip
- Stop: PMax-equivalent (MAvg - 3×ATR) at entry
- TP1: entry + 2R, close half
- TP2: entry + 4R, close rest
- Time stop: 120 bars

Hypothesis: trend-flip strategies leak edge in chop because they're always in.
Adding TP/time-stop discipline should improve PF without hurting WR.

### Proposal 003: Volume-confirmed mean reversion
**Status:** unbacktested · **Source:** synthesized 2026-05-08

ChartArt's RSI+BB strategy with a volume filter bolted on:
- Original triggers (RSI cross + BB cross simultaneous)
- PLUS: current bar's volume ≥ 1.3× 20-bar median (washout volume confirms capitulation)
- Stop: opposite BB · TP: BB middle (mean) at 1R
- Adds the missing volume primitive that all 4 external strategies skip

### Proposal 004 (TOP PRIORITY): Symbol-routed strategy stack
**Status:** unbacktested but data-backed · **Source:** synthesized from 11,760-combo
sweep, 2026-05-09

Don't pick ONE strategy — **route to the best strategy per symbol** based on
empirical fit. From the optimization findings:

| Symbol class | Route to | Why (empirical) |
|---|---|---|
| Tech/momentum (NVDA, MSFT, AMD, META, INTC, AMZN, TSLA, GS, BA, AAPL, AMD) | PMax (per-symbol params) | PMax median PF 2.16, all 16 symbols qualified, captures trend with MA-smoothed band |
| Defensive/index (SPY, IWM, XLF, HD) | Bollinger+RSI w/ `bb_length=20, bb_mult=1.5` | 91-97% WR on these names — they mean-revert cleanly within the short BB |
| Trend-rider on AAPL/COST | MACD+SMA200 | High PF (5-10) tolerable when paired with size discipline |

Implementation:
1. For each symbol, look up the winning (strategy, params) from `data/optimization_results.db::best_per_symbol`
2. Run that strategy with those exact params — no global config
3. New "router" agent picks the right detector + params per symbol on each evaluation tick

This is the cleanest application of the symbol-by-symbol parameter philosophy.

### Proposal 005: PMax + ATR breakout regime filter + TP/time-stop overlay
**Status:** unbacktested · **Source:** synthesized 2026-05-09

PMax is the most robust standalone (16/16 symbols), but its default exit is
"opposite signal forever," which leaks edge in chop. Borrow Empirical Breakout's
exit framework:

- **Entry:** PMax cross signal, with per-symbol-tuned params from optimizer
- **Stop:** the band at entry (PMax's natural stop)
- **TP1:** entry + 2R (close half)
- **TP2:** entry + 4R (close rest)
- **Time stop:** 60 bars (10 weeks of daily) on the assumption that if the trend
  hasn't paid 1R in that time, it never will
- **Long-MA regime gate:** only take longs when close > SMA(150); only take shorts
  when close < SMA(150) — eliminates the 60% of false flips in chop

This combines:
- Universal-best primary signal (PMax, frequency rank #1 in winners)
- Universal regime primitive (long-MA filter, frequency rank #5)
- Universal exit framework (TP/time-stop, only emp_breakout uses it currently)
- Per-symbol tuned params (the actual finding from this sweep)


---

## Proposed new strategies

(Ideas synthesized from the above. Tracked in `strategies/proposed/`.)

### Proposal 001: VIX-regime gap continuation
**Status:** unbacktested · **Source:** synthesized from DL post-mortem (2026-05-08)

Setup — all required at 10:00 ET:
- Prior-session VIX close ≥ 25
- |gap| > 0.5% from prior close
- First 30m bar closes in top 20% of range (LONG) or bottom 20% (SHORT)
- First 30m bar's direction matches gap direction
- First 30m volume ≥ 1.5× 20-day slot median

Trade:
- Entry: first 30m close (10:00 ET)
- Stop: opposite end of first 30m bar (~0.3–0.7%)
- Target: 1.5R
- Force exit: 14:30 ET

Hypothesis: stacking daily catalyst (gap + VIX) on intraday conviction
should compress the false-signal rate vs DL's intraday-only filter.

---

## Process — how a new strategy gets added

1. Drop the source (Pine Script `.pine`, or markdown spec `.md`) in `strategies/external/{slug}/source.{ext}`
2. Ask Claude: "analyze the strategy in `strategies/external/{slug}`"
3. Claude appends a section to **External strategies analyzed** above with:
   - Inputs the strategy expects (timeframe, indicators, lookback)
   - Entry/exit rules in plain English
   - What the author claims as performance
   - What primitives it uses (cross-reference the table above)
   - Honest critique: where it's likely overfit, what it depends on, how it'd hold up out-of-sample
4. If worth testing, Claude generates a Python detector in
   `agents/detectors/{slug}.py` that emits a `PatternResult` against
   30m or daily bars
5. The detector is run through the existing replay harness over
   the bellwether-16 / 4-year window
6. Results land in **External strategies analyzed**, with a green/yellow/red verdict
