# Day-trade picks — processing map (27 gated videos)

Classified from transcript intros. Efficiency: these collapse to ~6 mechanical archetypes; we backtest
each DISTINCT archetype (not 27 bespoke detectors), map each video to it, render winner/loser images,
and retire in _history.json with a verdict. "Opening-range family" was already tested exhaustively
(one_box_scalper + intraday_families C3/ORB + families A-D) → coin flip / net-losing over 20yr.

## Archetype clusters

### A. Opening-range / first-candle / 9:30 box (~15 — maps to tested family, expect NULL)
| video | channel | note |
|---|---|---|
| FEmD-hK1-yU | Scarface | One Box Scalper — **⭐ EXCEPTION / RETAINED**: coin flip unfiltered, but operator sees a clear winner-vs-loser pattern → kept as a **selection-filter candidate** (quantify feature → re-backtest filtered subset). Not rejected. |
| jq-fpkPv3-A | Scarface | 9:30 one-candle scalp (first-candle box variant) |
| FOVhnNiP8AI | Scarface | opening range strategy |
| ptcscbVgFC8 | Scarface | <90-min scalp schedule (box/ORB) |
| UFjajYgJBHg | IRONCLAD | 9:30 ORB — *coded & backtested in Python* (meta "do they work?") |
| dI4vQqDPM2E | Jdub | first-90-min, no-bias rules-based (opening range) |
| QEIYxl8XTiI | Jdub | opening scalp, first hours |
| lYThcYGUw7I | Jdub | first-candle scalp |
| 7teij9jI7mg | Jdub | ORB "foolproof" |
| seH8Y0RLyjA | Max Options | 15-minute ORB |
| F3dCfO6ME7M | Trader Tips | ORB + common mistakes |
| iLmF1DSP2Ls | Bull Barbie | ORB |
| EoQDQVblmMY | Rumers | "Box Theory" (opening box) |
| 9v_-z6aNkek | LuxAlgo | market-open momentum |
| TmiovtZxcKE | Kimmel | no-indicator, one-timeframe (likely box/ORB) |
| lxg-6QdBI6k | TradingLab | 10:00am specific setup (time-of-day) |

### B. Break-and-retest / price-action location (~3)
| RAMgdqP4gr4 | Tony Rockall | break & retest guide |
| voB7nFbpzxc | Oliver Velez | technique + *location* (supply/demand context; likely discretionary) |

### C. Candlestick pattern (1)
| RyTlRkMujuk | The Moving Average | **Three-Line Strike** reversal candle |

### D. Fast-indicator / EMA scalp (~2)
| PdJ5X0exfdU | HowToTrade | 9-EMA fast-momentum scalp |
| N7uP9V0Iktc | PBInvesting | two-indicator setup |

### E. Multi-indicator combo (~3)
| QUagyNxYlKg | Sean Solano | two custom indicators ($10k/mo) |
| TksyFwpNQ1g | The Rumers | "favorite indicator" mega-move (futures) |
| VnDWzRSuJxQ | Tyler Wilson | "perfect trade" futures setup |

### F. Multi-model 5-min scalp (1)
| Bdgev1or-7M | Trade with Pat | 5-min scalp, 3 entry models (72/77/86% claimed) |

### G. Generic beginner (1)
| 7Ds9djcEKB4 | Data Trader | "simplest day trading" (pro concepts simplified) |
| s0mPbbzc0CU | TraderNick | (transcript to read) |

## Plan
1. **Cluster A** → backtest a small set of representative ORB variants (plain 5m/15m ORB break-to-EOD,
   ORB + target/stop) alongside the done one_box_scalper; map all 15 to the result; render images. One
   detector set covers the cluster. Expect null (matches every prior ORB test).
2. **B–F distinct archetypes** → build one detector each (three-line-strike, 9-EMA pullback, break-retest,
   indicator combos), backtest on 1m/5m, render images. Reject the purely discretionary ones (Velez
   "location", vague "favorite indicator") with a documented reason — not mechanizable.
3. Retire every video in _history.json (passed/rejected) with its archetype + result; commit in batches.
