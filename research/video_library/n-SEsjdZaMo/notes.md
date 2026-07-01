# n-SEsjdZaMo — "Gap Up / Gap Down Strategy" (Humbled Trader)

Source: <https://www.youtube.com/watch?v=n-SEsjdZaMo> · ~25 min.

## Rules (mechanical)
- entry: Large-cap stock gaps up overnight over a key daily resistance on a positive catalyst (usually earnings beat). Long at the open on a pullback to the daily key level OR on a break of pre-market highs; reclaim VWAP at the open. Mirror short version: gap down through 52-wk-low / key support on negative earnings, short the bounces toward VWAP.
- exit/stop/target: stop = loss of 5-min VWAP (long) / reclaim of VWAP (short); targets = next daily resistance levels / scale out into resistance; intraday-to-few-days hold.
- filters/params: pre-market scanner, daily key levels, 52-wk-high/low breakout, earnings catalyst, VWAP (5-min), pre-market high/low.

## Verdict: ❌ REJECT — intraday earnings-gap execution (VWAP/pre-market levels, no intraday data)
Entry and risk are anchored to intraday mechanics we cannot reproduce on daily bars — pre-market highs, open-pullback to key level, 5-min VWAP reclaim/stop. The conceptual core (buy a large-cap gapping over a 52-wk-high on an earnings beat) could be a daily-bar earnings-gap-momentum idea, but the specific tradable edge described is the intraday entry/stop, and the daily skeleton overlaps heavily with our deployed Momentum Breakout (52-wk-high breakout). Not a clean novel daily spec.
Status: rejected, not deployed
