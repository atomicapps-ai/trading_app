# 2ElrQnn2cZE — "$1,600 into $350 MILLION" (Trading Notes)

Source: <https://www.youtube.com/watch?v=2ElrQnn2cZE> · ~11 min.

## Rules (mechanical)
- entry: Richard Dennis / Turtle trend-following, fully mechanical. Long when price breaks above the highest-high of the last 20 bars (Donchian 20 upper channel); the higher-timeframe variant uses a 55-bar breakout. Direction gated by a 200-period MA (only take breakouts in the direction of the 200MA — longs when price > 200MA).
- exit/stop/target: initial stop = entry candle close − 2 × ATR(20) (ATR length 20, SMA-smoothed). Exit/take-profit when price breaks the opposing 20-bar channel (e.g. for longs, exit when a prior 20-bar low is broken). Let winners run; small frequent losses, rare large wins.
- filters/params: all periods = 20 (Donchian high/low, ATR); 200MA trend filter; 55-bar channel option for higher timeframes. Risk ~2% per trade. Author demos on 1h but rules are timeframe-agnostic.

## Backtest (45 daily stocks, 10bps cost-in-R, long-only, OOS = 2nd half by trade time)
| variant | OOS n | win% | exp | PF | random-control PF |
|---|---|---|---|---|---|
| 20-day entry / 10-day exit | 1537 | 38.5% | +0.25R | 1.48 | 0.93 |
| 55-day entry / 20-day exit | 944 | 32.5% | +0.28R | 1.44 | 1.07 |

## Verdict: ⚠️ VALIDATED-BUT-REDUNDANT — real edge, overlaps deployed Momentum Breakout
The classic Turtle has a **genuine, OOS-robust trend-following edge** (PF ~1.44–1.48 OOS, clearly beating
its coin-flip control at 0.93) — low win rate, fat right tail, exactly as advertised mechanically (NOT the
"$350M" fantasy, and the win rate is ~35%, not high). BUT it is the **same long-side breakout family as the
deployed Momentum Breakout**, which is materially stronger (PF 2.34 with its volume+ADX confirmation and
regime gate). Adding a weaker, correlated breakout doesn't improve the book. Keep as a validated reference;
could be revisited only as a diversifier if we ever size a multi-breakout sleeve. Status: validated, not deployed.
