# Strategy Sourcing — where to mine tried-and-tested strategies (beyond YouTube)

Goal: broaden the input funnel for the mining pipeline (spec → backtest → correlation-gate → wire)
from YouTube to **higher-quality, community-reviewed, and semi-exclusive sources**. This is the
catalog + the sourcing strategy. Updated 2026-07.

## The sourcing strategy (how we pick + process)

A source is worth our time only if it scores on three axes:

1. **Mineable** — does it yield *mechanical, backtestable rules* (entry/exit/filter), or ideally
   ready code? A verified track record with no disclosed rules is lower-yield (we'd have to
   reverse-engineer).
2. **Vetted / reviewed** — is there an independent signal of quality? Best → worst:
   **live real-money track record** (C2/Darwinex/Composer/AllocateSmartly) > **editorial curation**
   (Quantpedia, AllocateSmartly) > **community upvotes/replies** (Reddit, QuantConnect) >
   **self-published, unreviewed** (random blog/Discord).
3. **Discovery difficulty** — the user's angle: semi-exclusive/private sources are less picked-over,
   so the edges are less crowded (paid databases, private Discords, prop communities, niche blogs).

**The funnel:** aggregators/meta-sources (find the good stuff cheaply) → verified-track-record
marketplaces + curated databases (highest signal) → practitioner blogs + shared-code platforms
(ready rules/code) → forums/Discords/social (raw, needs heavy vetting) → academic (highest quality,
highest effort).

**Non-negotiable:** every candidate is re-validated in our own rig (IS/OOS + random-direction
control + realistic costs) and correlation-gated before it goes near paper. "Reviewed" or "verified
track record" *lowers* our prior but never replaces independent backtesting — marketplaces have
heavy survivorship/selection bias (leaderboards show the lucky survivors).

## Tier 1 — highest signal (verified track records + curated databases)

| Source | What it is | Access | Vetting | Mineability |
|---|---|---|---|---|
| **Quantpedia** (quantpedia.com) | Encyclopedia of 900+ quant strategies distilled from academic papers, each with rules, backtest stats, drawdown, references. ~70 free; Premium = "less-known/unique." | Freemium / paid | Editorial curation + cited papers | **High** — rules are explicit; designed to be implemented |
| **Collective2** (collective2.com) | Marketplace of trading systems with **audited real-money/real-time track records**, Sharpe, drawdown, leverage. | Free to browse stats; paid to follow | **Live track record** + Trustpilot reviews | Medium — stats public, rules usually hidden (reverse-engineer from behavior) |
| **Darwinex** (darwinex.com / Darwinex Zero) | Traders' strategies wrapped as risk-standardized "DARWIN" indices; independent risk engine records real performance. | Free stats; invest to allocate | **Live, risk-normalized track record** | Medium — behavior/attribution visible, rules hidden |
| **Allocate Smartly** (allocatesmartly.com) | Tracks dozens of the best **Tactical Asset Allocation** strategies from books/papers with high-quality backtests + near-real-time signals. | Paid | Editorial curation + tracked live/backtest | **High** — TAA rules are published; monthly/weekly cadence (good for a swing/allocation sleeve) |
| **Composer** (composer.trade) | 3,000+ community "symphonies" (automated strategies) with backtests (Sharpe/DD) + live trading; big Discord. Third-party advanced search: icdb.solarwolf.xyz. | Freemium | **Live track record** + community + backtests | **High** — symphony logic is inspectable (rules are the strategy) |

## Tier 2 — practitioner blogs + shared-code platforms (ready rules/code)

| Source | What it is | Why it's good |
|---|---|---|
| **Quantocracy** (quantocracy.com) | **Meta-source**: curated daily mashup aggregating ~60+ quant blogs. | The force-multiplier — surfaces the best practitioner posts (many with backtests) so we don't crawl 60 blogs by hand |
| **QuantConnect** (quantconnect.com) | 1,200+ shared community algorithms + a Quantpedia strategy library (~350); open-source LEAN engine. | Ready **code** with backtests; largest quant community |
| **Robot Wealth** (robotwealth.com/blog) | Practitioner algo/FX/ML research, much of it free. | Rigorous, edge-focused, backtested |
| **Price Action Lab** (priceactionlab.com/Blog) | Quant trading articles, statistical-significance focus. | Skeptical, stats-driven (matches our control-vs-signal ethos) |
| **Alpha Architect** (alphaarchitect.com) | Factor/quant research firm blog; evidence-based. | Academic rigor, implementable factor strategies |
| **CSSA** (cssanalytics.wordpress.com) | Tactical/adaptive allocation research. | Original TAA/vol ideas |
| **QuantifiedStrategies** (quantifiedstrategies.com) | 100s of **free rule-based strategies with backtests** across markets/timeframes/styles ("numbers, no opinions"). | Very high mineability — explicit rules + stats, swing + intraday |
| **GitHub** (e.g. github.com/robcarver17) | Open-source backtests/strategies in Python/R/C++. | Complete codebases to adapt |

## Tier 3 — semi-exclusive / private (the user's angle: less crowded)

| Source | What it is | Notes |
|---|---|---|
| **Quantpedia Premium / Prime** | Paywalled 900+ "less-known/unique" strategies. | Semi-exclusive by paywall; institutional clients (GS/JPM) — low crowding |
| **SetupAlpha & RealTest strategy shops** (setupalpha.com) | Paid, professionally developed strategies **with 1–2 yrs live IBKR out-of-sample** + full rules + code. | Rules + code + live OOS — very high mineability; paid = semi-exclusive |
| **Paid Substack / newsletters** | Curated weekly backtested strategies (SetupAlpha, others via Quantocracy). | Variable; vet by track record + sample the free tier first |
| **Private / application-only Discords** | e.g. options/systematic rooms that started private, "apply to join." | **Highest vetting burden** — most are noise/signal-selling. Only pursue ones repeatedly recommended by r/algotrading with a real track record. Value is discussion + leads, not turnkey rules |
| **Prop-firm communities** (SMB Capital, Topstep, FTMO forums) | Communities around funded-trader programs. | Semi-private; more discretionary than systematic — lower mineability |
| **Elite Trader / Trade2Win / Wealth-Lab forums** | Decades of threads, strategy sharing, expert commentary. | Old-school, high signal in the archives; algo subforums |

## Tier 4 — academic (highest quality, highest effort)

- **SSRN** (papers.ssrn.com) — working papers; momentum/factor/anomaly strategies that later reach funds.
- **Google Scholar** + journals (Journal of Finance, RFS) — peer-reviewed.
- University working papers (MIT, Chicago Booth, LSE).
- *(Quantpedia already distills much of this into implementable form — start there, go to SSRN for depth.)*

## Recommended plan (what to hit first, and how)

1. **Wire Quantocracy as the daily meta-feed** — it aggregates the practitioner blogs; scan it for
   posts that publish explicit rules + backtests, queue those into the mining pipeline.
2. **Harvest QuantifiedStrategies + Quantpedia (free tier)** — both give explicit, rule-based,
   backtested strategies ready to spec → backtest in our rig. Highest immediate yield, lowest cost.
3. **Mine Composer + QuantConnect shared strategies** — ready logic/code with live/backtest track
   records; near-zero translation effort.
4. **Use Collective2 / Darwinex / Allocate Smartly for "what's actually working with real money"** —
   filter their leaderboards by long track record + low drawdown + acceptable leverage, then
   reverse-engineer or find the disclosed methodology; treat as *hypotheses*, not proven edges.
5. **Semi-exclusive last** — one or two paid sources (Quantpedia Premium, a RealTest shop) and only
   Reddit-vetted private Discords. Highest cost/effort; pursue once the free funnel is running.

**Discovery tactics for the hard-to-find sources:** search r/algotrading + r/quant for
"what's your edge / share your backtest" threads and for repeat community recommendations; follow
Quantocracy's blogroll to obscure authors; check who's top of Collective2/Darwinex leaderboards over
multi-year windows and find their writeups; mine forum archives (Elite Trader, Wealth-Lab) for
threads with posted equity curves.

## Integration with our pipeline

Each source maps onto the existing flow: **source → extract mechanical spec → backtest in the rig
(IS/OOS + control + cost) → correlation-gate vs the live book → wire (active:false) → review → enable.**
Sources that ship code (QuantConnect/Composer/GitHub/RealTest) skip the "translate from prose" step.
Sources with live track records raise our prior but we still independently validate — same discipline
that turned 41 mined videos into 4 honest passes.
