# Kronos Upgrade Proposal — TradeAgent

**Status:** DRAFT for review (2026-06-25). Nothing built yet.
**Goal:** Add Kronos-based forecasting to TradeAgent, rethink the navigation/UI around the
trade *lifecycle*, and stand up an honest process that decides whether a Kronos strategy
actually works — and, if so, what the real probability of profit vs. loss is.

This doc is the agreement artifact. Read it, mark it up, and once we agree we build.

---

## 0. What Kronos is (one paragraph)

Kronos (Tsinghua, AAAI 2026, MIT license, ~30k GitHub stars) is the first open-source
**foundation model for candlesticks**. A tokenizer quantizes OHLCV bars into discrete
tokens; a decoder-only transformer autoregressively predicts the next bars — GPT, but for
K-lines. Pre-trained on ~12B candles from 45 exchanges (stocks/futures/forex/crypto). Four
sizes: mini 4M, small 24.7M, base 102M (large 499M is closed). Context length 512 bars for
small/base. Crucially, **it is generative and probabilistic**: you sample N future paths
(Monte Carlo) at a chosen temperature, and from that distribution you read off direction,
P(profit), expected R, and a confidence band. That distribution is the single object that
powers all four roles below.

## 1. The honest evidence (what shapes the design)

The paper's headline (RankIC +93% vs. other foundation models) is a **statistical** metric
(MSE / RankIC / CRPS), **not** after-cost P&L. Two credible independent reads matter more:

- **Jonathan Kinlay (25-yr quant):** real transferable knowledge; best-defended use is
  *synthetic data generation* for stress-testing. But better MSE ≠ tradeable alpha —
  pre-training learns the *shape of noise* (volatility clustering), not conditional mean
  (direction). Demand a cost-aware backtest before trusting it.
- **Reproducible 497-trade test, 5-min BTC** (Kronos-small, 16 paths): out-of-sample it was
  **statistically indistinguishable from 1900s Brownian motion** (Brier 0.189 vs 0.188) and
  **badly calibrated** — said 2.4% when reality was 20%, said 84% when reality was 70%
  (~2× worse log-loss). Yet as a *directional* signal it fired 28% less and won
  **60.7% vs 49.1%**. So: weak as calibrated odds, decent as a directional vote.

**Three rules this forces on us:**

1. **Never trust Kronos's raw probabilities as truth.** Calibrate them against our own
   realized outcomes before any number drives sizing or is shown as "P(profit)".
2. **Shorter horizon = weaker.** 5-min was a coin flip. Start on **daily/swing** (where the
   existing random-search pipeline already lives), then earn the right to go intraday.
3. **Finetuning on our own bars is likely required** to fix the generic-distribution
   mismatch. The base checkpoint is a starting point, not the product.

## 2. The core idea: one forecast, four roles

A single inference per (symbol, interval, as_of_ts) produces a **ForecastDistribution**
object (N sampled OHLCV paths + derived stats). Every role consumes that one object — we
pay for inference once.

```
                         ┌─────────────────────────────┐
   bars (data_service) ─▶│  kronos_service.forecast()   │
   as_of_ts              │  → ForecastDistribution      │
                         │    • N paths (OHLCV)         │
                         │    • p_up, p_tp_before_sl    │
                         │    • expected_R, path σ      │
                         │    • quantile cone (10/50/90)│
                         └──────────────┬──────────────┘
            ┌───────────────┬───────────┴────────┬───────────────────┐
            ▼               ▼                    ▼                   ▼
     (A) Setup        (B) Probability     (C) Directional     (D) Synthetic
        Scanner            Engine            Analyst Voice       Data Gen
   rank universe by    calibrated         a detector/lens     stress-test +
   forecasted edge     P(profit), E[R],   that votes          augment thin
   → screener feed     confidence band    long/short/flat     backtests
```

**A. Setup scanner** — `scripts/kronos_scan.py` runs the forecast across the active universe
(`core_universe_100`), ranks symbols by forecasted edge (e.g. expected R × confidence),
and feeds the screener / a new "Kronos edge" tag. Answers "what looks best *right now*."

**B. Probability engine** — from the path distribution + a candidate plan's entry/stop/TP,
compute P(TP before SL), P(close > entry at deadline), expected R, and dispersion
(confidence). This is the number your "probability of profit vs loss" requirement needs —
but only *after* the calibration layer in §4.

**C. Directional analyst voice** — `agents/detectors/kronos_forecast.py`, written as a
**pure function of `(bars, config, as_of_ts)`** to match the existing detector contract so
the replay/backtest engine runs it unchanged. Emits a `Signal` (direction + conviction).
This is the lowest-risk use and the one the independent test actually supported.

**D. Synthetic data generator** — `services/kronos_synth.py` samples synthetic candle paths
to (1) stress-test strategies against regimes thin in history and (2) expand small backtest
samples. Quant-rated as the most defensible use; also feeds the Strategy Lab in §5.

## 3. Architecture — how it slots into the existing app

Nothing about the gates changes. Kronos is a **signal source + probability layer** in front
of the existing compliance → risk → human-ack → executioner flow.

| New component | Type | Responsibility |
|---|---|---|
| `services/kronos_service.py` | service | Wrap `KronosPredictor`; `forecast(symbol, interval, lookback, n_paths, T, top_p)` → `ForecastDistribution`. Per-(symbol,interval) cache + TTL like `data_service.refresh_if_stale`. CPU/MPS ok. |
| `models/forecast.py` | model | `ForecastDistribution` Pydantic schema (paths, quantiles, p_up, p_tp_before_sl, expected_R, sigma). |
| `agents/detectors/kronos_forecast.py` | detector | Pure-fn detector; distribution → `Signal`. Registered in `INTRADAY_DETECTORS` / swing registry. |
| `services/calibration_service.py` | service | Fit + apply predicted→realized probability map (isotonic/Platt); compute Brier, log-loss, ECE, reliability curve. |
| `scripts/kronos_scan.py` | script | Universe-wide ranking → screener feed. |
| `services/kronos_synth.py` | service | Synthetic path generation for Strategy Lab + augmentation. |
| `services/baseline_service.py` | service | Geometric-Brownian-motion fair-value baseline (the control to beat). |

Integration points that already exist and just get extended:
- **`probability_service.py`** — already blends backtest + live WR by sample size. Extend it
  to blend in the **calibrated** Kronos probability, weighted by how much calibration data
  we have. Single source of the number shown in the UI.
- **`portfolio_manager.py`** — Kronos `Signal` joins the consensus paths → `TradePlan`. TP
  legs can be *derived from the forecast cone* (TP1 at median-path first target, TP2 at the
  75th-percentile path), which is exactly the "auto-take-profit" the UI surfaces.
- **`TradeRecord` JSONL** — add Kronos fields inside the existing `setup_snapshot.entry_features`
  (no schema-breaking renames): `kronos_pred_prob`, `kronos_expected_R`, `kronos_path_sigma`,
  `calibrated_prob`, `baseline_prob`. This *is* the calibration dataset.
- **`executioner.py`** — unchanged. Auto-close at time-stop already exists; multi-leg TP +
  trailing already modeled. We're feeding it better plans, not changing the seam.

**Dependencies:** `torch`, `safetensors`, `huggingface_hub`, plus the `kronos` model code
(vendored from the MIT repo into `vendor/kronos/` or pinned). Inference is the only new
heavy dep; no GPU required for small/base at our volume.

## 4. The probability problem — can we estimate P(profit) *accurately*?

This is the crux of your question, and the honest answer is: **we don't assert it — we
measure it, and let the paper-trade data prove or disprove it.** The process is the answer.

**Step 1 — Raw prediction.** For every signal, Kronos gives a raw `p_win`. Treat as suspect.

**Step 2 — Log everything (shadow mode).** Before Kronos trades a cent, run it in **shadow**:
it predicts on every live signal, we log `(predicted_prob, baseline_prob, plan, actual_outcome,
P&L)` to the TradeRecord pool. No trades fired on it yet. This builds the calibration set the
same way the BTC test did.

**Step 3 — Calibrate.** Once enough paired paper trades accumulate, fit a calibration map
(isotonic regression / Platt scaling) from `predicted_prob → realized_win_rate`. Plot the
**reliability curve** (predicted on x, actual on y). A trustworthy model hugs the diagonal;
the BTC test's curve bowed badly (over-confident tails). `calibration_service` does this.

**Step 4 — Decide, with a number.** The honest verdict comes from three measurements:
- **Expected Calibration Error (ECE)** and the reliability curve — is predicted ≈ actual?
- **Brier score / log-loss vs. the Brownian baseline** on a chronological **out-of-sample**
  split — does it beat the control, or is it a coin flip?
- **Cost-aware profit factor / net R** on the paper trades — does the edge survive fees +
  slippage?

If the calibrated curve is near-diagonal **and** Brier beats baseline OOS **and** PF > target
after costs at the minimum sample size → we **show the calibrated P(profit)** and let it drive
sizing. If not → we **downgrade Kronos to a directional vote only**, hide the probability
number, and say so plainly. Either outcome is a real, defensible result.

**What "accurate" means here, concretely:** a calibrated probability is accurate if, across
many trades, signals tagged "70% win" actually win ~70% of the time (low ECE), and the score
beats the baseline out-of-sample. We can't promise that in advance — but we *can* promise to
measure it and not lie about it.

### 4a. How a single trade's probability is derived (and what it does/doesn't know)

The number shown per trade is built from a **clean price/volume spine plus displayed
context** — never one opaque blend. Decision (locked): the calibrated Kronos probability
stays the spine; news/sentiment/events are shown *beside* it, not folded into it.

```
   raw Kronos p_win        calibration shrink         final P(profit)
   (price/volume only) ──▶ (learned from logged   ──▶ shown + drives sizing
    73%                     paper trades)  −9%         64%
```

- **Recent volatility — already inside the number.** It lives in the high-low ranges of the
  candles and surfaces as the cone width / path σ. No separate volatility factor needed.
- **Daily news, sentiment, earnings, sector — context, not baked in.** Kronos never reads a
  headline, so we do not let news silently move the probability (that would make the number
  uncalibratable — the exact trap the 5-min BTC study fell into). Instead:
  - `news_service` + `sentiment_service` render a **news/sentiment flag** per candidate.
  - `earnings_service` is a **hard gate**: an earnings-blackout name is *removed* from the
    list, not down-weighted.
  - sector/regime context renders as an at-a-glance flag.
- **The human combines spine + context in one glance.** A calibrated 64% with a red earnings
  flag is a skip; a 61% that is calm + positive-news may rank ahead in your judgment even
  though it sits lower in the raw sort.

A possible later step — a separate, *separately-calibrated* "context-adjusted score" — is
explicitly deferred; we will not ship it until the pure spine is proven and calibratable.

## 5. The validation gauntlet (staged — "same gauntlet, different model")

Each stage is a gate. A strategy only advances if it clears the prior stage. Mirrors your
existing phase discipline and the reproducible-test ethos from the BTC study.

- **Stage 0 — Offline replay.** Reuse the replay engine. Kronos detector runs across daily
  bars on `core_universe_100`, cost-aware. **Gate:** beat *both* baselines (Brownian + the
  existing DL) on a chronologically-split OOS set. Curve-fit check: if it wins first half but
  ties/loses second half, it fails.
- **Stage 1 — Paper shadow.** Live, predicts but does not trade. Logs predicted vs. actual.
  **Gate:** accumulate ≥ N paired trades (propose N=100 to start) before any judgment.
- **Stage 2 — Calibration gate.** Reliability curve near-diagonal; ECE below threshold;
  Brier beats baseline OOS; PF > target after costs; win-rate ≥ threshold (recalibrate the
  old "80%" gate to something realistic, e.g. 55–60% with PF > 1.3, set from the data).
- **Stage 3 — Auto-approve on paper.** Enters the existing auto-approve flow (paper only;
  live stays hard-blocked + human-ack, unchanged).

**Metrics tracked throughout:** Brier, log-loss, ECE, reliability diagram, win-rate, profit
factor (after cost), expected R, IS-vs-OOS gap, delta vs. each baseline, sample size. These
become the Strategy Lab view (§6).

## 6. Navigation / UI rethink — organize around the trade lifecycle

The current sidebar is a feature list (Dashboard, Pending, Universe, Stock-lists,
Copy-insiders, Strategies, Trades, Broker, Console, Settings…). The rethink organizes around
the **funnel a trade actually travels**, which also answers "how do we go from a researched/
verified/high-probability trade to a running trade that auto-takes-profit."

**Proposed primary nav (the funnel):**

1. **Today** — command center: live equity/P&L, what's firing, open positions. (merges
   dashboard + live status bar)
2. **Scan** — the morning ranked list (see §6a). *Discovery.*
3. **Forecast** — pick a symbol → Kronos probability cone, P(profit), expected R,
   calibration-adjusted confidence, baseline comparison, chart. *Research/verify.*
4. **Approve** — the verified high-probability trade, **probability front and center**, one
   action to arm. (today's Pending, upgraded)
5. **Running** — live trades with the **auto-TP ladder visualized** (TP1/TP2 from the
   forecast cone), trailing stop, time-stop countdown. *The "auto-takes-profit" made visible.*
6. **Strategy Lab** — the gauntlet: backtests, OOS, **reliability curves**, per-strategy
   probability-trustworthiness scorecard, paper-trade calibration. (merges Strategies +
   backtests + new calibration views)

**Secondary "Tools" group (collapsed):** Copy-insiders, Stock-lists, Console, Broker, Settings.

The feedback loop is explicit: **Scan → Forecast → Approve → Running → (outcomes) → Strategy
Lab → recalibrate → better Forecast.** Calibration is not a hidden batch job; it's a visible
part of the product.

**Auto-take-profit mechanic (already mostly built, newly surfaced):** TP legs + trailing +
time-stop + executioner auto-close exist. We (a) derive the TP ladder from the Kronos cone,
(b) visualize it in Running, and (c) finally wire the entry-fill alert (the open Phase 6 item)
so the operator sees fill → armed TP → auto-close without watching the screen.

### 6a. The Scan view — morning funnel and at-a-glance decision surface

**The daily process:** each morning `kronos_scan.py` runs the forecast across all ~300
universe symbols → compliance gates remove earnings-blackout / halt / restricted names →
filter to calibrated **P(profit) > 60%** → **sort descending** (highest probability first).

**How many trades show:** only those that pass the gate — typically a *handful* (3–15, some
days zero). The list is short by design; the threshold does the filtering. Header shows the
funnel (e.g. "300 scanned · 47 forecast · 8 passed > 60%") so the operator trusts it. Full
passing set is scrollable; you are never scanning 300 rows.

**Each row, at a glance:** rank · symbol + direction · a calibrated P(profit) bar+number
(color-coded) · expected R · and three **context flags** that answer "should I look closer":
- volatility regime (calm / elevated) — `indicator_service`
- news / sentiment (positive / neutral / negative) — `news_service` + `sentiment_service`
- earnings proximity (clear / near) — `earnings_service`

Click a row → the Forecast detail (cone + auto-TP ladder + probability derivation from §4a).
A red earnings flag on a high-rank name is the kind of thing the operator catches in one
glance — which is the whole point of keeping context visible instead of buried in the number.

## 7. Build order (proposed)

1. `kronos_service` + `models/forecast.py` + vendored model → POC forecast on 3 daily symbols.
2. `baseline_service` (Brownian control) + `kronos_forecast` detector (pure fn).
3. Stage 0 offline replay on `core_universe_100`, cost-aware, vs. both baselines.
4. If it clears Stage 0: `calibration_service` + shadow-mode logging fields in TradeRecord.
5. Strategy Lab calibration view (reliability curve + scorecard).
6. Setup scanner + the nav/UI restructure (incremental — Today/Scan/Forecast/Approve/Running/Lab).
7. Synthetic-data generator into the backtest engine.

## 8. Decisions (locked 2026-06-25)

- **Probability model:** calibrated Kronos (price/volume) is the spine; news/sentiment/sector
  are displayed context; earnings is a hard gate. No context-adjusted blended score until the
  spine is proven. ✅ locked
- **Min sample N** before judging calibration: **100** paired paper trades. ✅
- **Stage 2 thresholds:** WR ≥ 55–60%, PF > 1.3 after costs, near-diagonal reliability curve,
  Brier beats Brownian OOS — final cutoffs tuned from the data, not the legacy 80%. ✅
- **Model size:** start **Kronos-small**; revisit base if edge is marginal. ✅
- **Finetune:** prove base-model Stage 0 first; finetune only if the generic distribution is
  the bottleneck. ✅
- **Rollout:** engine first; nav/UI restructure ships incrementally *after* Stage 0 proves
  there's something worth surfacing. ✅
