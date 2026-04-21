# Phase 4 Build Prompt — Agents
# Paste this entire prompt into VS Code Claude to begin Phase 4.
# Read CLAUDE.md and SKILL.md before writing any code. All rules apply.
# Revised 2026-04-20: workflow engine, Alpaca news, pure-function detectors.

---

## What Phase 4 delivers

The five trading agents plus a YAML-driven workflow engine:
universe_filter, analyst (4 lenses), portfolio_manager,
compliance_officer, and risk_manager (pre-trade).
The executioner and post-trade risk_manager land in Phase 6.

After Phase 4 the system can:
- Define and run user-composable workflows from `workflows/*.yaml`
- Screen stocks via Finviz scraper → scored shortlist
- Run pattern detection on daily + 1H bars from yfinance cache
- Score signals with PQS (Pattern Quality Score)
- Fetch real-time + historical news from Alpaca News API (Benzinga-sourced)
- Synthesize signals into TradePlan objects
- Run all compliance gates (C1–C8)
- Run all risk gates (R1–R9)
- Display real signals in the pending approvals queue

Phase 5 (new) adds the backtest engine that reuses every agent
built here. That is why the pure-function detector rule below is
a hard contract, not a suggestion — the same `detect_bull_flag()`
that fires live in Phase 4 must fire on a 2018 bar window in Phase 5.

---

## Architecture decisions for Phase 4

SWING FOCUS — all agents optimized for 2–10 day holds:
- Primary analysis timeframe: Daily bars
- Confirmation timeframe: 1H bars
- Pattern detection runs on COMPLETE candles (end-of-day)
- Agent pipeline runs TWICE per day by default (the user can add
  more workflows on other schedules via YAML):
    1. Post-market (16:30 ET): full analysis run → generates signals
    2. Pre-market (08:30 ET): refresh run → updates prices, re-scores

WORKFLOW COMPOSITION — the pre-gate pipeline is user-definable:
- Workflows live in `workflows/*.yaml` and define a DAG of agent steps
- A `WorkflowEngine` (new: `services/workflow_engine.py`) loads a YAML,
  resolves dependencies, and runs steps in order (parallelizing siblings)
- The compliance and risk gates are NEVER part of a workflow. They run
  automatically on every TradePlan produced by `portfolio_manager`.
  This is a hard invariant — no YAML can skip, reorder, or weaken them.
- Shipped workflows (Phase 4 seeds `workflows/` with these):
    - morning_run.yaml    — pre-market refresh at 08:30 ET
    - evening_run.yaml    — post-market full analysis at 16:30 ET
    - research_run.yaml   — manual trigger; research mode only

DATA SOURCES:
- OHLCV bars: yfinance (daily + 1H, cached in data/historical/) — free
- Universe filter: Finviz HTML scraper (free tier)
- News + headlines: Alpaca News API (Benzinga-sourced, free with Alpaca
  account, ~2015-present archive, real-time live feed). PRIMARY news source.
  Keys in .env: ALPACA_API_KEY, ALPACA_API_SECRET
- Fundamental filings: SEC EDGAR RSS (free, no key) — 8-K / 10-Q / 10-K
- News sentiment enrichment (OPTIONAL): Alpha Vantage (free, 25 calls/day)
  Used only when the analyst wants a numeric sentiment score on a
  symbol that already has Alpaca news present. Skipped if rate-limited
  or if ALPHA_VANTAGE_KEY is unset — workflow still passes.

NEWS DATA RATIONALE:
Alpaca's news endpoint was chosen over Alpha Vantage-as-primary because
(a) it has no daily cap, (b) it returns full headlines + bodies, not
just sentiment scores, and (c) its 2015+ archive enables news-aware
backtesting in Phase 5. An Alpaca account is free and does not require
moving broker execution off TradeStation — we use Alpaca for news/data
only, execution still routes through TradeStation per Phase 3.

UNIVERSE → SHORTLIST FLOW:
1. Finviz scraper returns full universe (80-300 symbols)
2. Fast pre-screener scores each symbol on 3 criteria:
   momentum score + volume score + volatility score
3. Top 50 symbols by pre-screen score advance to full analysis
4. Full pattern detection runs only on the top 50

PURE-FUNCTION DETECTOR RULE (Phase 5 prerequisite):
Every pattern detector and every analyst lens must be a pure function
of its inputs. Specifically:
- No calls to `datetime.now()`, `date.today()`, or any wall-clock source
- No broker lookups, no live API calls except through a passed-in
  data/news service that is itself time-scoped
- No module-level mutable state
- Given the same (bars, config, as_of_ts) inputs, return the same output
This is enforced because Phase 5 backtesting slides a window across
10+ years of bars and calls the exact same detector code that runs live.
Violations of this rule silently leak future information into backtests
and invalidate every result. See `## Pure-function contract` below for
the required function signatures.

---

## New environment variables (add to .env.example)

ALPACA_API_KEY=your_key_here          # primary news source (free with Alpaca account)
ALPACA_API_SECRET=your_secret_here
ALPHA_VANTAGE_KEY=                    # OPTIONAL sentiment enrichment; leave blank to skip
FINVIZ_DELAY_SECONDS=1.5              # politeness delay between Finviz requests
ALPACA_NEWS_DELAY_SECONDS=0.25        # rate-limit spacing for Alpaca News API

---

## New dependencies (add to requirements.txt)

yfinance>=0.2.40
pandas-ta>=0.3.14b           # technical indicators (RSI, ATR, BB, KC, VWAP)
requests>=2.32.0             # Finviz scraper + EDGAR RSS
beautifulsoup4>=4.12.0       # Finviz HTML parsing
lxml>=5.2.0                  # fast HTML parser for bs4
feedparser>=6.0.11           # EDGAR RSS parsing
alpaca-py>=0.30.0            # Alpaca News + market data client (news only; exec stays on TS)
vaderSentiment>=3.3.2        # lexicon-based headline sentiment (pure, offline, backtest-safe)

---

## Pure-function contract (read before writing any detector or lens)

Every pattern detector and every analyst lens MUST match this signature:

```python
def detect_<pattern>(
    daily: pd.DataFrame,   # daily bars, indicators already added, index tz-aware
    hourly: pd.DataFrame,  # 1H bars (may be empty if unavailable)
    config: dict,          # thresholds from strategy YAML
    as_of_ts: pd.Timestamp,  # the "now" the caller is simulating
) -> PatternResult | None:
    ...
```

Enforcement rules:

1. `as_of_ts` is the detector's ONLY source of "now". Never call
   `datetime.now()`, `date.today()`, `pd.Timestamp.now()`, or read
   any clock. All "is this recent" / "within N bars" logic derives
   from `as_of_ts`.
2. Before doing anything else, slice: `daily = daily.loc[:as_of_ts]`
   and `hourly = hourly.loc[:as_of_ts]`. Any bar at or after
   `as_of_ts + 1 minute` is a look-ahead bug.
3. Never call `yfinance` / `alpaca` / `httpx` directly inside a detector.
   News, fundamentals, and macro arrive as parameters from the analyst,
   which itself received them from a time-scoped service.
4. No module-level mutable state. No caches keyed on symbol. No class
   instance attributes that accumulate across calls. If a detector
   needs memoization, use `functools.lru_cache` on a pure helper.
5. Unit-test every detector with a hand-crafted bar frame plus a fixed
   `as_of_ts`, asserting the exact PatternResult. These tests become
   the regression safety net for Phase 5's backtest engine.

The analyst lenses follow the same contract:

```python
async def run_lens_<name>(
    symbol: str,
    bars: BarSet,               # daily + hourly, pre-indicator-added
    news: list[NewsItem],       # already filtered to ts <= as_of_ts
    fundamentals: list[Filing], # already filtered to ts <= as_of_ts
    macro: MacroContext,        # snapshot at as_of_ts
    config: dict,
    as_of_ts: pd.Timestamp,
) -> Signal | None:
    ...
```

News, fundamentals, and macro are always passed in — lenses never fetch.
`services/news_service.py` (Step 1.5 below) is the only place that
performs the live vs. historical dispatch, and it accepts `as_of_ts`
so Phase 5 can request "Alpaca news for NVDA as of 2021-03-15".

---

## Files to build (in order)

### Step 1 — services/data_service.py
OHLCV data layer. All agents call this — never yfinance directly.
Reads from data/historical/ cache. Downloads if missing.

```python
"""data_service.py — OHLCV bar cache layer.

All agents read bars through here. Never import yfinance outside this file.
Cache location: data/historical/{SYMBOL}_{interval}.csv
Intervals: '1d' (daily), '1h' (1-hour)

Key rule: never return an empty DataFrame silently.
Raise DataNotAvailableError so the caller knows to skip the symbol.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

HISTORICAL_DIR = DATA_DIR / "historical"

class DataNotAvailableError(Exception):
    """Raised when bars are not cached and download fails."""

async def get_bars(
    symbol: str,
    interval: Literal["1d", "1h"],
    as_of_ts: pd.Timestamp | None = None,  # Phase 5 backtests pass historical ts
    min_bars: int = 50,
    download_if_missing: bool = True,
) -> pd.DataFrame:
    """Return OHLCV DataFrame. Raises DataNotAvailableError if unavailable.

    Columns (lowercase): open, high, low, close, volume
    Index: DatetimeIndex, UTC-aware
    Sorted: ascending (oldest first)

    If as_of_ts is provided, the returned frame is sliced to
    `df.loc[:as_of_ts]` — never leak bars from after that timestamp.
    If as_of_ts is None (live mode), return the full cached frame.

    For 1h bars: downloads last 2 years of hourly data.
    For 1d bars: downloads last 20 years of daily data.
    """

async def refresh_bars(
    symbol: str,
    interval: Literal["1d", "1h"],
) -> pd.DataFrame:
    """Force re-download and cache. Returns updated DataFrame."""

async def get_bars_multi(
    symbols: list[str],
    interval: Literal["1d", "1h"],
    as_of_ts: pd.Timestamp | None = None,
    min_bars: int = 50,
) -> dict[str, pd.DataFrame]:
    """Batch fetch bars for multiple symbols.
    Returns dict of symbol → DataFrame (each sliced to as_of_ts if given).
    Symbols with errors are logged and omitted (no exception raised).
    """
```

Implementation notes:
- Use asyncio.to_thread() for all yfinance/file I/O (sync ops)
- Normalize all column names to lowercase on read
- Ensure index is DatetimeIndex with UTC timezone
- Cache files are CSV. Read with parse_dates=True, index_col=0
- For 1h bars: yfinance period="2y", interval="1h"
- For 1d bars: yfinance period="20y", interval="1d"
- Add a DATA_DIR import from settings_service

### Step 2 — services/news_service.py
Unified news + filings access. Alpaca News primary, EDGAR for filings.
All lenses read through here — never import alpaca-py or feedparser elsewhere.

```python
"""news_service.py — time-scoped news and filings access layer.

Single source of truth for news across live and backtest.
The `as_of_ts` parameter makes this safe for Phase 5 backtesting —
given a historical timestamp, return only items with published_at <= as_of_ts.

Alpaca News API:
  - Uses alpaca-py REST client (NewsClient)
  - Archive runs ~2015 to present, hourly granularity
  - No daily call cap; respect ALPACA_NEWS_DELAY_SECONDS between requests
  - Free with Alpaca account; broker execution still routes through TradeStation

EDGAR RSS:
  - feedparser on https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}&dateb=&owner=include&count=40&output=atom
  - Symbol → CIK lookup cached in data/edgar_cik_map.json
  - Use a polite 1s delay between requests; SEC asks for a real User-Agent with contact email
"""

class NewsItem(BaseModel):
    source: Literal["alpaca", "edgar"]
    symbol: str
    headline: str
    body: str | None
    published_at: pd.Timestamp    # UTC-aware
    url: str
    article_id: str               # source-specific id, unique within source

class Filing(BaseModel):
    symbol: str
    cik: str
    form_type: str                # "8-K", "10-Q", "10-K"
    filed_at: pd.Timestamp
    url: str
    title: str

async def get_news(
    symbol: str,
    as_of_ts: pd.Timestamp | None = None,
    lookback_hours: int = 72,
) -> list[NewsItem]:
    """Return Alpaca news for symbol in the window
    [as_of_ts - lookback_hours, as_of_ts]. as_of_ts=None means live/now.
    Cache hits to data/news_cache/{SYMBOL}/{YYYY-MM-DD}.jsonl (append-only by day)
    so Phase 5 backtests don't re-fetch the same archive segments.
    """

async def get_filings(
    symbol: str,
    as_of_ts: pd.Timestamp | None = None,
    lookback_days: int = 14,
    form_types: tuple[str, ...] = ("8-K", "10-Q", "10-K"),
) -> list[Filing]:
    """Return EDGAR filings in the window. Same as_of_ts semantics."""

async def get_news_multi(
    symbols: list[str],
    as_of_ts: pd.Timestamp | None = None,
    lookback_hours: int = 72,
) -> dict[str, list[NewsItem]]:
    """Batch news fetch. Errors per-symbol are logged and the symbol
    returns [] — do not raise."""
```

Implementation notes:
- alpaca-py imports: `from alpaca.data.historical.news import NewsClient`
  and `from alpaca.data.requests import NewsRequest`.
- NewsRequest supports `start` / `end` — use these to bound the window.
  Live mode (as_of_ts=None): `end=datetime.now(UTC)`, `start=end - timedelta(hours=lookback_hours)`.
- Cache strategy: for any (symbol, date) pair we've already fetched,
  read `news_cache/{symbol}/{date}.jsonl` instead of hitting the API.
  This is what makes news-aware backtesting cheap.
- EDGAR CIK lookup: first call per symbol fetches the CIK via the
  SEC ticker endpoint and writes to data/edgar_cik_map.json.
- All timestamps are UTC-aware Timestamps. If the source returns naive
  or ET-local, convert at the boundary.

### Step 3 — services/indicator_service.py
Technical indicator calculations using pandas-ta.
All agents use this — never call pandas_ta directly outside here.

```python
"""indicator_service.py — technical indicator calculations.

Wraps pandas-ta. All calculations take a DataFrame (from data_service)
and return a DataFrame with indicator columns appended.

Naming convention for returned columns:
  rsi_14, atr_14, atr_14_pct, vwap, sma_20, sma_50, sma_200,
  ema_20, bb_upper_20, bb_lower_20, bb_width_20,
  kc_upper_20, kc_lower_20,
  squeeze_on (bool), squeeze_fired (bool),
  momentum (TTM squeeze momentum histogram value),
  macd_line, macd_signal, macd_hist,
  volume_sma_20, volume_ratio (current / sma_20)
"""

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add all standard indicators to a bar DataFrame.
    Input df must have: open, high, low, close, volume columns.
    Returns df with indicator columns appended. Never modifies in place.
    """

def calc_squeeze(df: pd.DataFrame,
                 bb_period: int = 20, bb_mult: float = 2.0,
                 kc_period: int = 20, kc_mult: float = 1.5) -> pd.DataFrame:
    """Add squeeze columns: squeeze_on, squeeze_fired, momentum.
    squeeze_on = True when BB is inside KC (compression active).
    squeeze_fired = True on the first bar squeeze_on turns False
                    after being True for >= 6 bars.
    """

def calc_rsi_divergence(df: pd.DataFrame,
                        period: int = 14,
                        lookback: int = 50) -> pd.DataFrame:
    """Detect RSI divergence. Adds columns:
    bullish_div (bool), bearish_div (bool),
    div_class ('A', 'B', 'C', None),
    div_rsi_diff (float — RSI difference between lows/highs)
    """

def calc_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """Add session VWAP column. For daily bars, VWAP = rolling
    cumulative (price * volume) / cumulative volume, reset daily.
    For intraday bars, reset at session open each day.
    """
```

### Step 3 — agents/__init__.py
Empty init. Create agents/ directory at project root.

### Step 4 — agents/universe_filter.py
Finviz scraper → full universe → scored shortlist (top 50).

```python
"""universe_filter.py — Finviz HTML scraper + shortlist scorer.

TWO STAGES:
1. Finviz scraper: applies filter preset criteria to get full universe
2. Pre-screener: scores each symbol on momentum + volume + volatility,
   returns top 50 as the shortlist for full pattern analysis.

Finviz free tier scraping:
- URL: https://finviz.com/screener.ashx?v=111&f={filters}&r={row}
- Parse the results table with BeautifulSoup
- Paginate: 20 results per page, use &r= for offset
- Rate limit: FINVIZ_DELAY_SECONDS between requests (default 1.5s)
- User-Agent: set a real browser UA to avoid blocks
- Respect robots.txt — only scrape /screener.ashx

Filter URL parameter mapping (Finviz URL encoding):
  price_min / price_max  → fa_price_o{min}to{max}  (e.g. sh_price_o5to90)
  avg_volume_min 10M     → sh_avgvol_o10000
  market_cap mid         → cap_mid
  market_cap large       → cap_large
  sma50_relation above   → ta_sma50_pa (price above)
  sma200_relation above  → ta_sma200_pa
  rsi_min/max 50-80      → ta_rsi_b50o80
  exchange nasdaq        → exch_nasd
  exchange nyse          → exch_nyse
  eps_ttm_positive       → fa_eps_pos
  roe_positive           → fa_roe_pos

Finviz returns these columns per row (at minimum):
  Ticker, Company, Sector, Industry, Country, Market Cap,
  P/E, Price, Change, Volume

PRE-SCREENER scoring (0-100 per symbol, used to rank for shortlist):
  momentum_score (0-40 pts):
    + price above sma20: +10
    + price above sma50: +15
    + price above sma200: +15
  volume_score (0-30 pts):
    + relative_volume >= 1.5: +15
    + relative_volume >= 2.0: +30 (use higher)
    + volume_sma_20 >= 10M: +10 (but this is a filter gate so always met)
  volatility_score (0-30 pts):
    + atr_pct between 1.5-5.0: +30
    + atr_pct between 1.0-1.5 or 5.0-8.0: +15
    + outside that range: 0

Shortlist = top 50 symbols by total pre-screen score.
Ties broken by volume_score descending.
```

UniverseFilterResult model:
```python
class UniverseFilterResult(BaseModel):
    filter_id: str = Field(default_factory=lambda: str(uuid4()))
    ts_run: str
    preset_name: str
    mode: str
    universe: list[str]           # full filtered list
    universe_size: int
    shortlist: list[str]          # top 50 for full analysis
    shortlist_size: int
    total_screened: int
    rejected_count: int
    prescreener_scores: dict[str, float]  # symbol → score
    rejection_reasons: dict[str, int]     # reason → count
    elevated_risk_symbols: list[str]      # biotech etc.
    run_duration_seconds: float
```

Add UniverseFilterResult to models/__init__.py.
Save the latest result to data/universe_latest.json on every run.
The /universe router in Phase 5 reads this file.

### Step 5 — agents/analyst.py
Four lenses → Signal objects. Runs on shortlist only.

```python
"""analyst.py — multi-lens signal generator.

Runs four lenses in parallel (asyncio.gather) for each symbol.
Each lens returns 0 or 1 Signal objects.
Only signals with PQS >= 55 (strength >= 0.55) are emitted.

LENS 1: technical (primary for swing focus)
  Runs 9 pattern detectors from pattern_recognition.md.
  Uses daily bars as primary, 1H bars for confirmation.
  PQS computed per pattern_recognition.md scoring rules.

LENS 2: fundamental
  Reads SEC EDGAR RSS for recent filings (8-K, 10-Q, 10-K).
  Checks for: earnings_surprise, guidance_revision,
  insider_buying, analyst_upgrade.
  Returns signal only if a material event found in last 14 days.

LENS 3: sentiment
  Reads news items from services/news_service.get_news() — never
  calls any HTTP endpoint directly. The lens is a pure function of
  (news, as_of_ts, config).

  Primary scoring (no external call):
    - Filter items to published_at within config.lookback_hours of as_of_ts
      (default 72h; configurable via strategy YAML)
    - Require >= config.min_articles qualifying items (default 2)
    - Base sentiment = VADER compound score averaged across headlines
      (uses nltk's VaderSentiment — add `vaderSentiment>=3.3.2` to deps)
    - Weight each article by recency (linear decay across lookback window)
    - Returns signal only if |weighted_sentiment| >= config.min_abs_sentiment
      (default 0.3)

  Optional Alpha Vantage enrichment (skip cleanly if disabled):
    - If settings.analyst.use_av_sentiment is True AND ALPHA_VANTAGE_KEY
      is set AND today's AV call count < 25, call AV News Sentiment
      for the top shortlisted symbols (max 20/day to leave headroom).
    - Blend: final_sentiment = 0.6 * vader + 0.4 * av_sentiment
    - If AV is unavailable for any reason, fall back silently to VADER.
    - Call count tracked in data/av_call_count.json (resets nightly).
    - Cache AV responses in data/sentiment_cache/{SYMBOL}_{YYYY-MM-DD}.json.

  Backtest note: because news_service.get_news honors as_of_ts and
  caches per-day, Phase 5 can replay historical sentiment without
  ever calling a live API — the cache becomes the dataset. AV
  enrichment is disabled in backtest mode (25/day cap makes it
  impractical); VADER-only sentiment runs on the cached Alpaca
  headlines.

LENS 4: macro
  No external API calls — uses SPY and VIX data from yfinance cache.
  Computes:
    spy_trend_20d: SPY 20-day return (positive/negative)
    spy_above_sma200: bool
    vix_level: latest VIX close
    vix_regime: 'low' (<15), 'medium' (15-25), 'high' (25-35), 'extreme' (>35)
    sector_rs: sector ETF (XLK/XLF/etc.) 20-day return vs SPY
  Returns a macro_context dict attached to every Signal from other lenses.
  Does NOT return its own Signal — provides context only.
"""
```

Pattern detectors to implement (one function per pattern).
Each detector signature:
```python
def detect_{pattern_name}(
    daily: pd.DataFrame,  # daily bars with indicators
    hourly: pd.DataFrame, # 1H bars with indicators (may be empty)
    config: dict,         # thresholds from strategy config YAML
) -> PatternResult | None:
    """Returns PatternResult if pattern detected, None otherwise."""
```

PatternResult model:
```python
class PatternResult(BaseModel):
    pattern_name: str
    detected: bool
    direction: Literal["long", "short"]
    pqs_base: int
    pqs_modifiers: dict[str, int]   # modifier_name → points
    pqs_total: int                  # capped at 100
    entry_price: float
    stop_price: float
    tp1_price: float
    tp2_price: float
    invalidation_level: float
    invalidation_condition: str
    evidence_items: list[dict]
    watchlist_candidate: bool = False  # True if partial pattern
    unmet_conditions: list[str] = []   # conditions not yet met
```

Implement these 9 detectors using the exact rules from pattern_recognition.md.
Load all numeric thresholds from config dict (not hardcoded) so they can be
tuned via strategy YAML without code changes:

1. detect_bull_bear_flag(daily, hourly, config)
2. detect_double_bottom_top(daily, hourly, config)
3. detect_rsi_divergence(daily, hourly, config)
4. detect_ascending_descending_triangle(daily, hourly, config)
5. detect_inside_bar_nr7(daily, hourly, config)
6. detect_cup_and_handle(daily, hourly, config)
7. detect_volatility_squeeze(daily, hourly, config)
8. detect_vwap_reclaim(daily, hourly, config)
9. detect_wyckoff_accumulation(daily, hourly, config)

After running all detectors, check combination bonuses from
pattern_recognition.md Section "Confluence combinations":
  combo_1: wyckoff + squeeze → +25 pts on higher scorer
  combo_2: ascending_triangle + rsi_divergence → avg + 15 pts
  combo_3: bull_flag + vwap_reclaim → higher + 12 pts
  combo_4: cup_and_handle + squeeze in handle → avg + 18 pts
  combo_5: double_bottom + class_A_rsi_divergence → avg + 20 pts

Universal confluence modifiers (from pattern_recognition.md):
Apply these to every pattern's PQS after pattern-specific modifiers:
  volume confirmation: +10 or +15 pts
  RSI alignment: +8 and/or +5 pts
  MA alignment: +8 and +7 pts
  VWAP alignment: +8 pts (1H patterns only — swing focus skips this)
  market structure (S/R level): +10 pts
  no earnings within 7 days: +5 pts
  VIX below 25: +5 pts
  sector alignment: +7 pts
  SPY trend alignment: +5 pts

Full analyst run function:
```python
async def run_analyst(
    symbol: str,
    strategy_config: dict,
    macro_context: dict,
) -> list[Signal]:
    """Run all 4 lenses on symbol. Return qualifying signals (PQS >= 55)."""
```

### Step 6 — agents/compliance_officer.py
Gates C1–C8. Exact logic from SKILL.md §3 (Agent 4).

```python
"""compliance_officer.py — hard gate, veto authority.

Implements gates C1–C8 from SKILL.md.
Each gate is a method returning ComplianceVerdict | None.
None = PASS. Non-None = BLOCK (return immediately, skip remaining gates).

IMPORTANT: In research/paper mode, gates C1 (halt), C2 (LULD), C3 (SSR)
are advisory only — we don't have real-time market state from yfinance.
Gates C4 (wash sale), C5 (PDT), C6 (restricted list), C7 (earnings
blackout), C8 (plan completeness) run in all modes.
"""

class ComplianceOfficer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def check(
        self,
        plan: TradePlan,
        account: AccountState,
        market_state: MarketState,
    ) -> ComplianceVerdict:
        """Run all gates in sequence. Return on first BLOCK."""
        gates = [
            self._c1_halt_check,
            self._c2_luld_check,
            self._c3_ssr_check,
            self._c4_wash_sale_check,
            self._c5_pdt_check,
            self._c6_restricted_list_check,
            self._c7_earnings_blackout_check,
            self._c8_plan_completeness_check,
        ]
        evaluated: list[ComplianceGate] = []
        for gate in gates:
            gate_id = gate.__name__.split("_")[1].upper()  # "c1", "C1" etc.
            evaluated.append(gate_id)
            verdict = gate(plan, account, market_state)
            if verdict is not None:
                return verdict
        return ComplianceVerdict(
            plan_id=plan.plan_id,
            result="pass",
            gates_evaluated=evaluated,
        )

    def _c1_halt_check(self, plan, account, ms) -> ComplianceVerdict | None:
        """Gate C1: Trading halt check.
        Advisory in research/paper (no real-time halt data).
        """

    def _c2_luld_check(self, plan, account, ms) -> ComplianceVerdict | None:
        """Gate C2: Limit-Up / Limit-Down band check.
        Advisory in research/paper.
        """

    def _c3_ssr_check(self, plan, account, ms) -> ComplianceVerdict | None:
        """Gate C3: Short Sale Restriction (Reg SHO).
        Advisory in research/paper.
        Only applies to short trades.
        """

    def _c4_wash_sale_check(self, plan, account, ms) -> ComplianceVerdict | None:
        """Gate C4: Wash Sale Rule — IRC §1091.
        Active in all modes. Check account.wash_sale_window list.
        """

    def _c5_pdt_check(self, plan, account, ms) -> ComplianceVerdict | None:
        """Gate C5: Pattern Day Trader rule.
        Only applies to margin accounts with equity < $25,000.
        Only applies to intraday holding period.
        Swing trades (holding_period != 'intraday') skip this gate.
        """

    def _c6_restricted_list_check(self, plan, account, ms) -> ComplianceVerdict | None:
        """Gate C6: Restricted symbols list (from settings.yaml)."""

    def _c7_earnings_blackout_check(self, plan, account, ms) -> ComplianceVerdict | None:
        """Gate C7: Earnings blackout window.
        Uses market_state.earnings_within_hours.
        Skip if compliance.earnings_blackout_enabled == False.
        """

    def _c8_plan_completeness_check(self, plan, account, ms) -> ComplianceVerdict | None:
        """Gate C8: TradePlan completeness.
        Verify all required fields are non-null.
        Required: instrument, thesis, setup, risk, execution,
                  setup.entry.price, setup.stop_loss.initial.price,
                  setup.take_profit (non-empty, sums to 100),
                  risk.r_per_share > 0,
                  risk.position_size_shares > 0.
        """
```

### Step 7 — agents/risk_manager.py
Gates R1–R9 pre-trade. Post-trade postmortem in Phase 5.

```python
"""risk_manager.py — hard gate (pre-trade) + postmortem (Phase 5).

Implements gates R1–R9 from SKILL.md.
Gates R1 and R2 may RESIZE (reduce position size) before rejecting.
Gates R3–R9 REJECT outright.
All gate decisions are logged with reason and gate ID.
"""

class RiskManager:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def pre_trade_check(
        self,
        plan: TradePlan,
        account: AccountState,
    ) -> RiskVerdict:
        """Run R1–R9. May resize or reject. Returns RiskVerdict."""
        rd = self._settings.risk_defaults
        original_size = plan.risk.get("position_size_shares", 0)
        approved_size = original_size
        triggered: list[RiskGate] = []

        # R1: per-trade risk cap → resize
        # R2: notional cap → resize
        # (run both resizes, take minimum approved size)

        # R3: daily loss cap → reject
        # R4: max open positions → reject
        # R5: max daily trades → reject
        # R6: sector concentration → reject
        # R7: minimum R:R → reject
        # R8: participation rate cap → resize
        # R9: spread too wide → reject (in paper/live; advisory in research)

        # implement all 9 gates with exact SKILL.md logic

    def _r1_per_trade_risk_cap(self, plan, account, rd) -> int | None:
        """Returns approved_size or None if no resize needed.
        Docstring: Gate R1: per-trade risk cap."""

    # ... all 9 gate methods with docstrings citing SKILL.md rule
```

### Step 8 — agents/portfolio_manager.py
Synthesizes signals → TradePlan objects.

```python
"""portfolio_manager.py — signal synthesizer and trade planner.

Receives signals from all analyst lenses for a symbol.
Rules (from SKILL.md §3 Agent 3):
  - Minimum 2 lenses must agree in direction before generating a TradePlan
  - If existing position in symbol: evaluate add/hold/reduce, not just new entry
  - Max 5 concurrent TradePlan proposals awaiting compliance/risk
  - Must query memory store for similar past setups
  - Conviction = weighted average of contributing signal strengths

TradePlan construction rules for SWING trades:
  entry: type='limit', valid_until='gtc', price = best technical entry level
  stop_loss.initial: price = pattern invalidation level from highest PQS signal
  stop_loss.trail: mode='atr', atr_multiple=1.5, activate_after='price >= entry + 1.5R'
  stop_loss.time_stop: close if no progress within 5 sessions
  take_profit[0]: size_pct=50, price=tp1 from highest PQS pattern
  take_profit[1]: size_pct=50, price=tp2 from highest PQS pattern
  
  position sizing formula (from SKILL.md §2.5):
    R = entry_price - stop_price
    position_size_shares = floor((equity × risk_pct_per_trade/100) / R)
    position_notional = position_size_shares × entry_price
    position_risk_pct = (position_size_shares × R) / equity × 100
    
  tradingview_chart_url:
    f"https://www.tradingview.com/chart/?symbol={exchange}:{symbol}&interval=D"
    Use exchange='NASDAQ' for Nasdaq, 'NYSE' for NYSE stocks.
"""

class PortfolioManager:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pending_count = 0  # tracks plans awaiting approval

    async def process_signals(
        self,
        symbol: str,
        signals: list[Signal],
        account: AccountState,
        existing_positions: list[str],
    ) -> TradePlan | None:
        """Main entry. Returns TradePlan or None if criteria not met."""
```

### Step 9 — services/workflow_engine.py (NEW)
YAML-driven workflow runner. Replaces the hardcoded pipeline sequence.

```python
"""workflow_engine.py — composable agent workflow runner.

Loads workflows/*.yaml and executes the step DAG. Each step names
an agent (or built-in op) and its parameters. Siblings (steps with
identical depends_on sets) run in parallel via asyncio.gather.

HARD INVARIANTS (cannot be expressed or overridden in YAML):
  1. compliance_officer runs on every TradePlan produced by any
     step. The engine injects it after the terminal step.
  2. risk_manager runs after compliance_officer on pass verdicts only.
  3. Verdicts are written to SQLite pending_approvals regardless
     of outcome (approved, blocked, resized).
  4. The workflow cannot define steps named 'compliance_officer' or
     'risk_manager' — they are not user-composable.

Available step kinds (Phase 4):
  fetch_news         → calls news_service.get_news_multi
  fetch_filings      → calls news_service.get_filings for shortlist
  filter_universe    → calls universe_filter agent (returns shortlist)
  compute_macro      → computes MacroContext once per run
  analyze            → runs analyst lenses on each shortlist symbol
                       (parallelized across symbols; lenses configurable)
  plan               → runs portfolio_manager on each symbol with signals

Each step receives the accumulated `WorkflowContext` (prior step
outputs keyed by step id) and returns its own output, which is
merged into the context for downstream steps.
"""

class WorkflowContext(BaseModel):
    workflow_id: str
    run_id: str
    mode: Literal["research", "paper", "live"]
    as_of_ts: pd.Timestamp        # pipeline "now"; live = datetime.now(UTC)
    outputs: dict[str, Any] = {}  # step_id → output

class WorkflowStep(BaseModel):
    id: str
    kind: Literal["fetch_news", "fetch_filings", "filter_universe",
                  "compute_macro", "analyze", "plan"]
    params: dict[str, Any] = {}
    depends_on: list[str] = []

class Workflow(BaseModel):
    workflow_id: str
    description: str
    schedule: str | None = None     # optional cron string for APScheduler
    default_mode: Literal["research", "paper", "live"] = "paper"
    steps: list[WorkflowStep]

class WorkflowEngine:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def load(self, path: Path) -> Workflow:
        """Parse + validate a workflow YAML. Rejects any step named
        'compliance_officer' or 'risk_manager'."""

    async def run(
        self,
        workflow: Workflow,
        mode: str | None = None,
        as_of_ts: pd.Timestamp | None = None,  # Phase 5 backtests pass historical
    ) -> WorkflowRunResult:
        """Execute the DAG. Returns summary with per-step timing and
        the full list of TradePlans proposed + their gate verdicts."""
```

Seed three workflows in `workflows/`:

`workflows/morning_run.yaml`:
```yaml
workflow_id: morning_run
description: Pre-market refresh — re-score existing shortlist with updated bars
default_mode: paper
schedule: "30 8 * * 1-5"   # 08:30 ET Mon-Fri (cron in server TZ; ET normalization in scheduler)

steps:
  - id: filter_universe
    kind: filter_universe
    params:
      preset: liquid_momentum_core
  - id: fetch_news
    kind: fetch_news
    params:
      lookback_hours: 18
    depends_on: [filter_universe]
  - id: compute_macro
    kind: compute_macro
    depends_on: [filter_universe]
  - id: analyze
    kind: analyze
    params:
      lenses: [technical, fundamental, sentiment, macro]
    depends_on: [fetch_news, compute_macro]
  - id: plan
    kind: plan
    depends_on: [analyze]
```

`workflows/evening_run.yaml`:
```yaml
workflow_id: evening_run
description: Post-market full analysis — generates signals for next session
default_mode: paper
schedule: "30 16 * * 1-5"  # 16:30 ET Mon-Fri
steps:
  - id: filter_universe
    kind: filter_universe
    params:
      preset: liquid_momentum_core
  - id: fetch_news
    kind: fetch_news
    params:
      lookback_hours: 72
    depends_on: [filter_universe]
  - id: fetch_filings
    kind: fetch_filings
    params:
      lookback_days: 14
    depends_on: [filter_universe]
  - id: compute_macro
    kind: compute_macro
    depends_on: [filter_universe]
  - id: analyze
    kind: analyze
    params:
      lenses: [technical, fundamental, sentiment, macro]
    depends_on: [fetch_news, fetch_filings, compute_macro]
  - id: plan
    kind: plan
    depends_on: [analyze]
```

`workflows/research_run.yaml`:
```yaml
workflow_id: research_run
description: Manual research run — technical-only, no news, no filings
default_mode: research
# no schedule — manual trigger only
steps:
  - id: filter_universe
    kind: filter_universe
    params:
      preset: liquid_momentum_core
  - id: compute_macro
    kind: compute_macro
    depends_on: [filter_universe]
  - id: analyze
    kind: analyze
    params:
      lenses: [technical, macro]
    depends_on: [compute_macro]
  - id: plan
    kind: plan
    depends_on: [analyze]
```

### Step 10 — services/pipeline_service.py (thin orchestrator)
```python
"""pipeline_service.py — thin wrapper around WorkflowEngine.

Loads the workflow YAML by id, runs it via WorkflowEngine, then
applies the hardcoded compliance + risk gates to every TradePlan
the workflow emits. Writes outcomes to SQLite and fires ntfy.

Called by:
  - POST /api/workflows/{id}/run (manual trigger from UI)
  - APScheduler (schedules derived from workflow.schedule fields)

Run status tracked in data/pipeline_status.json:
  {
    "status": "running | idle | error",
    "last_workflow_id": "evening_run",
    "last_run_ts": "iso8601",
    "last_run_duration_seconds": 42.1,
    "last_run_symbols_analyzed": 50,
    "last_run_signals_generated": 12,
    "last_run_plans_proposed": 4,
    "last_run_plans_approved": 3,
    "last_run_plans_blocked": 1,
    "error_message": null
  }
"""

async def run_workflow_by_id(
    workflow_id: str,
    mode: str | None = None,
    as_of_ts: pd.Timestamp | None = None,
    settings: Settings = ...,
) -> PipelineRunResult:
    """Load workflow YAML, run via engine, apply gates, persist results."""

async def list_workflows(settings: Settings) -> list[Workflow]:
    """Read all workflows/*.yaml and return parsed metadata."""
```

### Step 10 — SQLite schema (data/app.db)
Create tables via aiosqlite in a new services/db_service.py.

Tables needed in Phase 4:

```sql
-- Pending approval queue (replaces stub data in routers/pending.py)
CREATE TABLE IF NOT EXISTS pending_approvals (
    plan_id TEXT PRIMARY KEY,
    ts_created TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    strategy TEXT NOT NULL,
    conviction REAL NOT NULL,
    plan_json TEXT NOT NULL,        -- full TradePlan JSON
    compliance_verdict_json TEXT,   -- ComplianceVerdict JSON
    risk_verdict_json TEXT,         -- RiskVerdict JSON
    status TEXT DEFAULT 'pending',  -- pending | approved | rejected | expired
    ack_action TEXT,                -- approve | reject | modify
    ack_ts TEXT,
    mode TEXT NOT NULL
);

-- Pipeline run history
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id TEXT PRIMARY KEY,
    ts_start TEXT NOT NULL,
    ts_end TEXT,
    preset_name TEXT,
    mode TEXT,
    symbols_analyzed INTEGER,
    signals_generated INTEGER,
    plans_proposed INTEGER,
    plans_approved INTEGER,
    plans_blocked TEXT,             -- JSON list of {plan_id, reason}
    error_message TEXT,
    status TEXT DEFAULT 'running'   -- running | complete | error
);

-- Trade memory (queryable past setups for portfolio_manager)
CREATE TABLE IF NOT EXISTS trade_memory (
    trade_id TEXT PRIMARY KEY,
    plan_id TEXT,
    symbol TEXT,
    strategy_name TEXT,
    sector TEXT,
    direction TEXT,
    win INTEGER,                    -- 1 = win, 0 = loss
    pnl_r_multiple REAL,
    mfe_r REAL,
    mae_r REAL,
    rsi_14_at_entry REAL,
    atr_pct_at_entry REAL,
    vix_at_entry REAL,
    vix_regime TEXT,
    sma50_distance_pct REAL,
    sma200_distance_pct REAL,
    volume_vs_avg_ratio REAL,
    spy_trend_20d TEXT,
    entry_features_json TEXT,       -- full feature vector JSON
    learning_tags_json TEXT,        -- JSON list of strings
    ts_entered TEXT,
    ts_exited TEXT,
    mode TEXT
);
```

db_service.py must:
- Create tables on first run (ensure_tables() called in lifespan)
- Expose async CRUD for pending_approvals:
    get_pending_plans() → list[dict]
    get_plan_by_id(plan_id) → dict | None
    upsert_plan(plan, compliance_verdict, risk_verdict) → None
    ack_plan(plan_id, action) → None
    expire_stale_plans(timeout_minutes) → int  # returns count expired
- Expose async write for pipeline_runs
- Expose async write/read for trade_memory

### Step 11 — Update routers/pending.py
Replace STUB_PENDING reads with real SQLite reads.

```python
# Replace all STUB_PENDING references with db_service calls
# GET /pending → reads from pending_approvals table, status='pending'
# GET /pending/{plan_id} → reads single plan from table
# POST /pending/{plan_id}/ack → calls db_service.ack_plan()
#                               Phase 5 will then fire executioner
```

### Step 12 — Add workflow + pipeline routes
New file: routers/workflows.py

```
GET  /api/workflows                    → list all workflows (id, description, schedule)
POST /api/workflows/{id}/run           → trigger a workflow manually
GET  /api/workflows/{id}               → full YAML content (for editor preview)
GET  /api/pipeline/status              → read data/pipeline_status.json
GET  /api/universe/latest              → read data/universe_latest.json
```

Add to app.py: `app.include_router(workflows.router)`

### Step 13 — Update routers/stubs.py
Remove the /universe stub route (now handled by workflow-driven pipeline).
Universe page still shows placeholder since full UI is Phase 6,
but the /api/universe/latest endpoint is now real.

### Step 14 — services/scheduler.py (create if missing)
APScheduler wires the `schedule:` field on each workflow YAML into
a job. There is no hardcoded schedule list — add a workflow with a
cron string and the scheduler picks it up on next load.

```python
"""scheduler.py — APScheduler loader that reads workflow schedules.

On startup (FastAPI lifespan):
  1. Read all workflows/*.yaml via WorkflowEngine.load()
  2. For each workflow with a `schedule:` field, register a job:
       func: pipeline_service.run_workflow_by_id(workflow_id)
       trigger: CronTrigger from workflow.schedule (ET timezone)
  3. Reload on /api/workflows/{id}/save (future — Phase 6 edit UI)

Use AsyncIOScheduler from APScheduler.
Timezone: America/New_York for every workflow schedule.
Log every registered job at startup so the user can verify in logs.
"""
```

---

## Strategy config YAML (create one for testing)

Create strategy_configs/swing_momentum.yaml:

```yaml
strategy_name: swing_momentum
version: "1.0"
description: Multi-pattern swing strategy, 2-10 day holds
universe_filter_preset: liquid_momentum_core
mode: paper
active: true
holding_period: swing_days

risk:
  max_risk_pct_per_trade: 0.50
  max_position_pct_of_equity: 8.0
  min_rr_ratio: 2.0

pattern_thresholds:
  bull_flag:
    flagpole_min_atr_multiple: 3.0
    flag_retracement_min_pct: 30.0
    flag_retracement_max_pct: 60.0
    flag_duration_min_bars: 3
    flag_duration_max_bars: 20
    trigger_volume_ratio_min: 1.5

  double_bottom:
    prior_downtrend_min_pct: 15.0
    second_low_tolerance_pct: 3.0
    rsi_divergence_min_diff: 3.0
    breakout_volume_ratio_min: 1.5

  rsi_divergence:
    rsi_period: 14
    min_rsi_diff: 3.0
    max_rsi_at_low: 40.0
    class_a_rsi_ceiling: 30.0

  ascending_triangle:
    min_resistance_touches: 2
    resistance_tolerance_pct: 0.5
    breakout_zone_min_pct: 50.0
    breakout_volume_ratio_min: 1.5

  inside_bar_nr7:
    mother_candle_min_atr_ratio: 0.75
    max_bars_before_trigger: 5

  cup_and_handle:
    cup_depth_min_pct: 15.0
    cup_depth_max_pct: 50.0
    cup_duration_min_weeks: 7
    handle_depth_max_pct: 20.0
    breakout_volume_ratio_min: 1.5

  volatility_squeeze:
    bb_period: 20
    bb_mult: 2.0
    kc_period: 20
    kc_mult: 1.5
    min_squeeze_bars: 6

  vwap_reclaim:
    min_bars_above_vwap_before_break: 8
    max_consolidation_bars: 8
    reclaim_volume_ratio_min: 1.5

  wyckoff_accumulation:
    sc_volume_min_ratio: 2.0
    spring_max_undercut_pct: 5.0
    spring_volume_max_ratio: 0.75
    range_min_weeks: 6
```

---

## Verification checklist

- [ ] agents/ directory exists with all 5 agent files
- [ ] services/data_service.py exists, get_bars(symbol, "1d") works for SPY
- [ ] services/data_service.py get_bars(..., as_of_ts=2020-01-01) returns
      only bars <= 2020-01-01 (no look-ahead leak)
- [ ] services/news_service.py exists; get_news("AAPL") returns live items;
      get_news("AAPL", as_of_ts=2022-06-01) returns only items <= that ts
- [ ] services/indicator_service.py exists, add_indicators() runs
- [ ] services/workflow_engine.py exists, rejects workflow YAML that
      names a step 'compliance_officer' or 'risk_manager'
- [ ] services/pipeline_service.py exists and calls WorkflowEngine
- [ ] services/db_service.py exists, ensure_tables() runs at startup
- [ ] SQLite tables created: pending_approvals, pipeline_runs, trade_memory
- [ ] workflows/ contains morning_run.yaml, evening_run.yaml, research_run.yaml
- [ ] GET /api/workflows lists all three workflows with schedules
- [ ] POST /api/workflows/evening_run/run returns 200 (even if no signals)
- [ ] GET /api/pipeline/status returns current status JSON
- [ ] GET /api/universe/latest returns last universe result
- [ ] GET /pending reads from SQLite (no more STUB_PENDING)
- [ ] ComplianceOfficer runs on EVERY TradePlan (verify via log); no
      workflow YAML can bypass it
- [ ] RiskManager runs on every plan that passes compliance
- [ ] ComplianceOfficer.check() blocks a plan on a restricted symbol
- [ ] RiskManager.pre_trade_check() resizes an oversized position
- [ ] PortfolioManager requires 2+ lenses before generating TradePlan
- [ ] All 9 pattern detectors accept `as_of_ts` and return PatternResult|None
- [ ] Every detector has a unit test with a fixed bar frame + fixed as_of_ts
      asserting the PatternResult (these are the Phase 5 safety net)
- [ ] No detector imports `datetime`, `time`, `yfinance`, `httpx`, or calls
      `.now()` anywhere (grep check passes)
- [ ] swing_momentum.yaml exists in strategy_configs/
- [ ] Alpaca news cache directory exists at data/news_cache/
- [ ] Sentiment cache directory exists at data/sentiment_cache/
      (only populated when AV enrichment is enabled)
- [ ] Scheduler logs show jobs registered for every workflow with a schedule
- [ ] yfinance bars download for at least SPY without error
- [ ] No pattern detector raises an unhandled exception on empty data

---

## Important implementation notes

1. NEVER crash the pipeline on a single symbol failure.
   Every loop over symbols must be wrapped in try/except.
   Log the error and continue to the next symbol.

2. Alpaca News is the primary source and has no daily cap. Alpha
   Vantage is OPTIONAL enrichment; if ALPHA_VANTAGE_KEY is unset
   or the 25/day limit is reached, the sentiment lens falls back
   to VADER-only scoring on Alpaca headlines — workflow continues.

3. Pattern detectors receive DataFrames that may have < 50 bars
   for recently-listed stocks. Every detector must check
   len(df) >= min_required_bars and return None if insufficient.
   Cup and handle requires the most: at least 200 daily bars.

4. The portfolio_manager tracks pending_count against the limit
   of 5 concurrent proposals. Check the SQLite pending_approvals
   table for count of status='pending' before generating a new plan.

5. For swing trades, the 1H bar data is used ONLY for confirmation
   of patterns found on daily bars. If hourly data is unavailable
   for a symbol, run pattern detection on daily only (no crash).

6. Finviz scraping: if the scraper gets a 429 or 503, back off
   exponentially (2s, 4s, 8s) and retry up to 3 times.
   If all retries fail, log the error and use the last cached
   universe result from data/universe_latest.json.

7. The macro lens (VIX + SPY context) should be computed ONCE
   per workflow run (via the compute_macro step) and passed to
   every analyze step through the WorkflowContext.

8. All agent classes take Settings in __init__. Never call
   get_settings() inside agent methods — use self._settings.

9. TradePlan.mode must match the workflow run mode. A plan
   generated in a research workflow must have mode='research'.

10. After Phase 4, the pending page will show REAL plans from
    SQLite. The stub data in services/stub_data.py is NOT removed
    yet — it is still used by the dashboard widget for open
    positions and activity feed (those become real in Phase 6).

11. PURE-FUNCTION ENFORCEMENT — add a pre-commit grep that fails
    if `agents/**/*.py` contains any of: `datetime.now`, `date.today`,
    `time.time`, `pd.Timestamp.now`, `yfinance.`, `httpx.`, `requests.`,
    `alpaca.`. The only allowed "now" is the `as_of_ts` parameter.
    (Can be a simple Makefile target or a `scripts/lint_agents.py`.)

12. Compliance and risk gates CANNOT be named in a workflow YAML.
    WorkflowEngine.load() must raise on any step with
    kind == 'compliance_officer' or kind == 'risk_manager'.
    They are injected by pipeline_service AFTER the workflow's
    terminal `plan` step, on every TradePlan emitted.
