# Un-ingested video backlog — triage by title

The `day_intra` lane is **exhausted** (30/30 assessed, all rejected). There are
**23 discovered-but-un-ingested** videos (lane `—`, no transcript yet). The
sandbox **cannot pull their transcripts** — YouTube IP-blocks cloud IPs
(`RequestBlocked`), and yt-dlp isn't installed. So these must be ingested on the
operator's machine (residential IP) via the `/mining` "Add a video" flow or
`python -m scripts.video_ingest <url> --ingest`, then pushed for me to assess.

Titles resolved via web search (can't read transcripts). Classified for the
**day-trade** goal (swing content is out of scope for this hunt):

## 🎯 Day-trade leads worth ingesting (novel or unclear mechanism)
| id | title | note |
|---|---|---|
| ~~qkChxbuUqvU~~ | ~~Gap Trading Prints You Money (Gap Up/Down/Fill)~~ | ❌ **TESTED → REJECTED.** Backtested directly on 595 equities / 20y / up-to-564k trades: every config net-negative (best net PF 0.92). No edge. See GAP_BACKTEST.md. |
| R5paDQRdk0c | The PROVEN 1-Hour Trading Strategy 85% Win Rate | intraday (1H); 85% WR claim is hype but mechanism unknown — worth a look |
| H-2T8Uh7Nfw | Try This Simple Pullback Trading Strategy - 75% Win Rate | pullback; may be intraday |

## ↩️ Day-trade but redundant / already-rejected mechanism
| id | title | why skip |
|---|---|---|
| 8P9BHSVD_vI | How To Trade The Opening Range Breakout (ORB) | ORB — exhaustively tested, fails OOS |
| gXGw8IC9dFQ | 63% Win Rate 20 EMA Pull Back Strategy | EMA-pullback — already rejected (7Ds9djcEKB4) |
| v4qwe618tuw | Copy This 5 Rule SMC Trading Strategy | SMC/ICT — AMD variant already rejected (Bdgev1or-7M) |

## 🪃 Swing / daily / position (out of scope — not day trades)
| id | title |
|---|---|
| eK2yatANcNU | Mean Reversion Trading Strategy Clearly Explained |
| 9nefht65xxE | MOST Profitable Breakout Strategy Tested 3000× (Darvas) |
| 6NWcKpupjJo | 3 Momentum Trading Strategies (Backtests & Rules) |
| NojfYk31_xI | 7 Algo Trading Strategies (Backtest And Rules) |
| gX8FjjKR7ec | 6 Larry Connors Trading Strategies (daily MR) |
| c9-SIpy3dEw | Mean Reversion (BB+RSI+ADX) — 179% Profit |
| OKl208tuiIs | The Only Swing Trading Strategy You Need |
| 8EmDCJUgnrw | 3 ETF Trading Strategies (Backtest & Rules) |
| j1qjX0Zxpd0 | 3 Profitable Trading Strategies (Backtest & Rules) |
| 0kJ_fWP5fKU | 3 Proven Trend Strategies for Huge Gains! |
| FdU3q1wspbk | (trend-following strategies) |
| -6lPuMFSMG0 | Martin Luk's Winning Strategy (USIC swing champion) |

## 🚫 Meta / education / not a strategy
| id | title |
|---|---|
| ZX-Tp4zgJYc | Every Trading Strategy Explained in 12 Minutes (overview) |
| W722Ca8tS7g | The 4 backtesting techniques behind WINNING strategies |
| YFzlBQCeynQ | Cascade ordering strategy (grid/martingale EA — avoid) |

## ❓ Title not resolvable via search
| id |
|---|
| LsLv-m1AAK4 |
| hVpKSBUp4zk |

## Takeaway
Only ~3 of the 23 are genuinely novel day-trade leads, and **Gap trading
(qkChxbuUqvU)** is the standout — a distinct intraday mechanism we don't have,
and one I can backtest directly on cached equity data without needing the
transcript. The rest are swing/daily (the QuantifiedStrategies + USIC-champion
cohort) or redundant ORB/EMA/SMC.
