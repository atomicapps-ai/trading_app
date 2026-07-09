# Transcript — UFjajYgJBHg
<https://www.youtube.com/watch?v=UFjajYgJBHg>

[00:00:00 | 0s] If you're a trader, you probably watched
[00:00:02 | 2s] videos about 9:30 a.m. trading
[00:00:03 | 3s] strategies, also known as the orb
[00:00:06 | 6s] strategy. And every trading guru has
[00:00:08 | 8s] their own version of it. But have you
[00:00:10 | 10s] ever wondered whether any of these
[00:00:11 | 11s] versions actually work? Me, too. So, I
[00:00:14 | 14s] coded and back-tested those strategies
[00:00:16 | 16s] in Python to reveal the truth. And in
[00:00:18 | 18s] that process, I found something in the
[00:00:20 | 20s] data that no guru is telling you. And
[00:00:23 | 23s] that one thing got me a setup that
[00:00:24 | 24s] returned 531%
[00:00:27 | 27s] over 5 years. And I'm going to share all
[00:00:29 | 29s] the results. If you watch this video
[00:00:31 | 31s] from start to end, you'll realize
[00:00:33 | 33s] everything you know about the 9:30 a.m.
[00:00:35 | 35s] strategy is wrong. Let's get into it.
[00:00:37 | 37s] So, what is the 9:30 a.m. strategy? Even
[00:00:40 | 40s] if you already know it, stick with me.
[00:00:42 | 42s] I've seen a lot of people think they
[00:00:44 | 44s] know it, but actually don't. At 9:30
[00:00:47 | 47s] a.m. Eastern Standard Time, you mark the
[00:00:49 | 49s] high and low of a specific candle. For
[00:00:51 | 51s] example, a 15-minute candle. That high
[00:00:54 | 54s] and low range is called the opening
[00:00:56 | 56s] range.
[00:00:57 | 57s] Then you watch to see if candle breaks
[00:00:59 | 59s] out and closes out of that range using
[00:01:01 | 61s] the same time frame or a lower one.
[00:01:04 | 64s] The basic assumption is that whichever
[00:01:05 | 65s] direction price breaks out, it will
[00:01:07 | 67s] continue in that direction.
[00:01:10 | 70s] So, you enter in the direction of the
[00:01:11 | 71s] breakout, in this case, long position.
[00:01:14 | 74s] Place a limit order at the edge of the
[00:01:16 | 76s] range. Stop loss goes on the opposite
[00:01:18 | 78s] side of the range, and take profit is
[00:01:21 | 81s] set at a predefined risk-reward ratio,
[00:01:23 | 83s] like 1:2 or 1:3.
[00:01:26 | 86s] Now, this is the most basic version. But
[00:01:28 | 88s] here's where it gets interesting. Every
[00:01:31 | 91s] guru claims this basic version doesn't
[00:01:33 | 93s] work. And that you need their specific
[00:01:36 | 96s] secret to make it profitable.
[00:01:38 | 98s] Some say you need to wait for a retest
[00:01:40 | 100s] before entering. Others say wait for a
[00:01:42 | 102s] fair value gap during the breakout, or
[00:01:44 | 104s] use candlestick patterns, and etc.
[00:01:47 | 107s] And not only that, they all say
[00:01:49 | 109s] different things about which time frame
[00:01:50 | 110s] to use, where to put your stop loss,
[00:01:53 | 113s] what risk-reward ratio to go with, and
[00:01:55 | 115s] etc.
[00:01:57 | 117s] There's even a guy named Casper who
[00:01:58 | 118s] posts a 9:30 a.m. strategy video almost
[00:02:01 | 121s] every month and his setup changes every
[00:02:04 | 124s] single time.
[00:02:05 | 125s] So, which version actually works? That's
[00:02:08 | 128s] what we're going to find out. So, the
[00:02:10 | 130s] first version I tested was from this
[00:02:12 | 132s] video. In this video, Casper tells us to
[00:02:15 | 135s] use the retest candle. His main argument
[00:02:17 | 137s] is that you shouldn't enter right at the
[00:02:19 | 139s] breakout. Instead, you have to wait.
[00:02:22 | 142s] Wait for price to come back, retest the
[00:02:24 | 144s] range, and only enter once that retest
[00:02:27 | 147s] candle closes outside the range.
[00:02:30 | 150s] He says this is what separates winners
[00:02:32 | 152s] from losers.
[00:02:33 | 153s] For the rest of the rules, he stick to
[00:02:35 | 155s] 5-minute candles for everything. Put
[00:02:38 | 158s] stop loss at the midpoint of the range
[00:02:40 | 160s] and uses a 1:2 risk to reward.
[00:02:43 | 163s] He also claims this works on every
[00:02:45 | 165s] asset.
[00:02:46 | 166s] So, is that true?
[00:02:47 | 167s] I backtested it over 10 years on ES, NQ,
[00:02:51 | 171s] gold, and euro futures. For commissions,
[00:02:54 | 174s] I used NinjaTrader fees. And for
[00:02:56 | 176s] slippage, I set it 1.5 ticks per trade.
[00:03:00 | 180s] For those of you who don't know
[00:03:01 | 181s] commissions and slippage, Google it and
[00:03:03 | 183s] put it into your head because it's
[00:03:04 | 184s] really important concept that affects
[00:03:06 | 186s] your performance directly when trading.
[00:03:09 | 189s] And here are the results for each asset.
[00:03:12 | 192s] For ES, minus 66% in 10 years. NQ, plus
[00:03:17 | 197s] 14% in 10 years, which is better than
[00:03:19 | 199s] ES, but still not profitable enough.
[00:03:22 | 202s] Gold, minus 50%. Euro, minus 97%.
[00:03:27 | 207s] It was complete garbage on every single
[00:03:29 | 209s] asset.
[00:03:31 | 211s] And here's where it gets really
[00:03:33 | 213s] interesting.
[00:03:34 | 214s] Casper posted this video in February
[00:03:36 | 216s] 2026 and to back up his strategy, he
[00:03:39 | 219s] showed a 1-month backtest claiming it
[00:03:41 | 221s] was profitable.
[00:03:43 | 223s] And you know what? He wasn't lying.
[00:03:46 | 226s] Look at this.
[00:03:47 | 227s] This is the actual equity curve for the
[00:03:49 | 229s] 1-month period leading up to when he
[00:03:50 | 230s] posted the video.
[00:03:52 | 232s] You can see that strategy actually did
[00:03:54 | 234s] perform well on ES and NQ during that
[00:03:57 | 237s] time.
[00:03:58 | 238s] But if you extend this curve by two more
[00:04:00 | 240s] month from when he posted the video to
[00:04:02 | 242s] early April, watch what happens.
[00:04:05 | 245s] The line that was going up, it crashed
[00:04:08 | 248s] all the way back down. So, if you
[00:04:10 | 250s] watched his video and started trading
[00:04:11 | 251s] right after, you would have gotten
[00:04:13 | 253s] absolutely crushed.
[00:04:15 | 255s] And more importantly, that nice little
[00:04:17 | 257s] profitable stretch from January to
[00:04:19 | 259s] February,
[00:04:20 | 260s] when you put it back into the full
[00:04:22 | 262s] 10-year picture, it's basically nothing.
[00:04:25 | 265s] Just a tiny blip on an equity curve
[00:04:27 | 267s] that's been losing money slowly for
[00:04:29 | 269s] years.
[00:04:30 | 270s] And the same exact pattern showed up in
[00:04:32 | 272s] his other video, the one where he says
[00:04:34 | 274s] you need to use fair value gap to trade
[00:04:36 | 276s] the 9:30 a.m. strategy. In that video,
[00:04:39 | 279s] too, he runs a 1-month backtest and
[00:04:41 | 281s] claims it's profitable. But when I
[00:04:44 | 284s] tested it long-term, the results were
[00:04:46 | 286s] bad. -20% in ES over 10 years, +18% in
[00:04:51 | 291s] NQ, which is profitable but extremely
[00:04:53 | 293s] low profit,
[00:04:54 | 294s] -24% in gold, and -77% in euro. And just
[00:05:00 | 300s] like before, it just happened to be
[00:05:02 | 302s] profitable in the month leading up to
[00:05:04 | 304s] when he posted the video.
[00:05:06 | 306s] At this point, the pattern is pretty
[00:05:08 | 308s] clear. It looks like he cherry-picks
[00:05:10 | 310s] setups that happen to work in the month
[00:05:12 | 312s] before he posts and uses that 1-month
[00:05:14 | 314s] backtest to make the strategy look
[00:05:16 | 316s] profitable. And this is exactly why you
[00:05:19 | 319s] can't trust a quick backtest done by
[00:05:21 | 321s] hand in TradingView. You need to
[00:05:23 | 323s] backtest properly on a long enough time
[00:05:25 | 325s] period.
[00:05:26 | 326s] Now, let's look at the next one, a guru
[00:05:28 | 328s] named Scarface. His main difference from
[00:05:31 | 331s] Casper is that he looks at the shape of
[00:05:33 | 333s] the retest candle.
[00:05:35 | 335s] Casper just enters at the retest candle
[00:05:37 | 337s] close, no matter what. But Scarface only
[00:05:40 | 340s] enters if the candle shape confirms the
[00:05:43 | 343s] direction. For example, since price
[00:05:45 | 345s] break above the range, this is a long
[00:05:47 | 347s] setup. So, Scarface want to see a
[00:05:49 | 349s] bullish retest candle.
[00:05:51 | 351s] In this case, this candle retest the
[00:05:54 | 354s] range and it's bullish.
[00:05:56 | 356s] Perfect. Scarface enters. But here in
[00:05:59 | 359s] the second case, this candle retest the
[00:06:01 | 361s] range perfectly, but it's not bullish.
[00:06:04 | 364s] So, Scarface skip the trade. Casper
[00:06:06 | 366s] would have entered here without a second
[00:06:08 | 368s] thought, and that's the difference
[00:06:10 | 370s] between these two setups. There are some
[00:06:12 | 372s] other small differences, too, like stop
[00:06:14 | 374s] loss and time frames, but I'll skip
[00:06:16 | 376s] those to keep this video from getting
[00:06:18 | 378s] too long.
[00:06:19 | 379s] Just like Casper, he claims this works
[00:06:22 | 382s] on every asset. And to back it up, he
[00:06:25 | 385s] shows a one-year backtest with a clean
[00:06:27 | 387s] upward equity curve. So, easy, right?
[00:06:30 | 390s] When I ran his exact setup, results
[00:06:32 | 392s] actually looked great over the past year
[00:06:34 | 394s] in S&amp;P, gold, and euro.
[00:06:37 | 397s] This equity curve shows what you'd get
[00:06:39 | 399s] if you traded Scarface's setup on all
[00:06:42 | 402s] three of these markets over the past
[00:06:44 | 404s] year.
[00:06:45 | 405s] But here's the catch. This equity curve
[00:06:47 | 407s] assumes zero commissions and zero
[00:06:50 | 410s] slippage.
[00:06:51 | 411s] Once you factor those costs in, that
[00:06:54 | 414s] profitable last year, it made almost no
[00:06:56 | 416s] money.
[00:06:57 | 417s] And when you extend it to the full 10
[00:06:59 | 419s] years with realistic cost, minus 98%
[00:07:03 | 423s] complete disaster.
[00:07:05 | 425s] So, here's what we just learned.
[00:07:08 | 428s] Scarface was using a good-looking
[00:07:09 | 429s] one-year backtest in his video, but once
[00:07:12 | 432s] you factor in transaction costs, that
[00:07:14 | 434s] one year wasn't actually that
[00:07:16 | 436s] profitable.
[00:07:18 | 438s] And in the long term, the strategy
[00:07:19 | 439s] returned minus 98.79%
[00:07:22 | 442s] over 10 years.
[00:07:25 | 445s] Last one, J Dub Trades.
[00:07:27 | 447s] He uses the five-minute candle to define
[00:07:29 | 449s] the opening range and the one-minute
[00:07:31 | 451s] candle for entries.
[00:07:33 | 453s] But he's not really clear on whether you
[00:07:34 | 454s] enter right at the retest or wait to see
[00:07:37 | 457s] the price action. The video kind of
[00:07:39 | 459s] leaves it ambiguous.
[00:07:41 | 461s] So, I tested both versions, and just
[00:07:43 | 463s] like the others, wasn't profitable on
[00:07:45 | 465s] ES, better in NQ, but still not
[00:07:47 | 467s] profitable. Wasn't profitable in gold,
[00:07:50 | 470s] wasn't profitable in euro. This strategy
[00:07:53 | 473s] also didn't work in any asset.
[00:07:55 | 475s] At this point, two questions came to
[00:07:57 | 477s] mind. First, what if the simplest
[00:08:00 | 480s] version of the 9:30 a.m. strategy
[00:08:02 | 482s] actually works better? Remember that
[00:08:04 | 484s] basic version of the 9:30 a.m. strategy
[00:08:07 | 487s] that I mentioned at the beginning of
[00:08:08 | 488s] this video?
[00:08:09 | 489s] No retest, no FVG, no candlestick
[00:08:12 | 492s] patterns, just placing a limit order at
[00:08:15 | 495s] the range right after price breaks out.
[00:08:18 | 498s] Second, what if the entry rules from
[00:08:20 | 500s] these gurus are fine, but they're just
[00:08:22 | 502s] using the wrong settings?
[00:08:24 | 504s] For example, Casper uses the 5-minute
[00:08:26 | 506s] candle to define the range and to enter.
[00:08:28 | 508s] But what if you use the 15-minute for
[00:08:30 | 510s] the range and the 5-minute for entries
[00:08:32 | 512s] instead?
[00:08:33 | 513s] Or take Scarface, he uses 1:2
[00:08:35 | 515s] risk-to-reward ratio, but what about 1:1
[00:08:38 | 518s] or 1:3 or 1:4?
[00:08:42 | 522s] So, I tested all of it. And that's how I
[00:08:44 | 524s] finally found a strategy that's actually
[00:08:47 | 527s] profitable.
[00:08:49 | 529s] To do this, I took every single thing in
[00:08:51 | 531s] the 9:30 a.m. strategy that you can
[00:08:53 | 533s] change and turn them into a variable.
[00:08:56 | 536s] First variable is the entry setup. There
[00:08:59 | 539s] are four options I tested. Three are
[00:09:01 | 541s] what the gurus talked about: retest,
[00:09:03 | 543s] fair value gap, and candlestick.
[00:09:06 | 546s] And the fourth is the basic version of
[00:09:07 | 547s] 9:30 a.m. strategy.
[00:09:10 | 550s] Second variable is the time frame.
[00:09:13 | 553s] There are actually two time frames here.
[00:09:15 | 555s] One is for defining the opening range.
[00:09:17 | 557s] Other is for watching the breakout and
[00:09:20 | 560s] entering.
[00:09:21 | 561s] If that sounds confusing, here's what it
[00:09:23 | 563s] means. Let's say your range time frame
[00:09:25 | 565s] is 15-minute and your entry time frame
[00:09:27 | 567s] is 5-minute.
[00:09:29 | 569s] That means you take the high and low of
[00:09:30 | 570s] the first 15-minute candle starting at
[00:09:33 | 573s] 9:30 a.m. and then you watch the
[00:09:35 | 575s] 5-minute candle to see if price breaks
[00:09:37 | 577s] out of that range.
[00:09:39 | 579s] Now, if both time frames are 5 minutes,
[00:09:41 | 581s] you take the high and low of the first
[00:09:43 | 583s] 5-minute candle, and you also watch the
[00:09:45 | 585s] 5-minute candle for the breakout. I
[00:09:47 | 587s] tested every possible combination of
[00:09:49 | 589s] these time frames to see which one works
[00:09:52 | 592s] best.
[00:09:53 | 593s] Third variable is where to put your stop
[00:09:55 | 595s] loss.
[00:09:56 | 596s] There are a lot of options here. You can
[00:09:58 | 598s] put it at the midpoint of the range, at
[00:10:00 | 600s] the opposite side of the range, or if
[00:10:02 | 602s] you're using the retest setup, you can
[00:10:04 | 604s] set it at the wick of the retest candle.
[00:10:07 | 607s] There are even more, but you get the
[00:10:09 | 609s] idea. I tested all of them.
[00:10:12 | 612s] Fourth variable is the risk to reward
[00:10:14 | 614s] ratio.
[00:10:15 | 615s] Every single guru tells you to use 1:2,
[00:10:18 | 618s] but I don't think that's necessarily
[00:10:20 | 620s] right. So, I tested 1:1, 1:2, 1:3, and
[00:10:24 | 624s] 1:4.
[00:10:26 | 626s] Fifth variable is the cutoff time.
[00:10:28 | 628s] This is the time after which you stop
[00:10:30 | 630s] looking for entries for the day.
[00:10:32 | 632s] For example, if the cutoff time is 11:00
[00:10:35 | 635s] a.m. and you haven't entered by 11:00
[00:10:37 | 637s] a.m., you don't take any trades that
[00:10:39 | 639s] day. You just wait for the next day.
[00:10:42 | 642s] I tested four cutoff times: 10:00 a.m.,
[00:10:45 | 645s] 11:00 a.m., 12:00 p.m., and 1:00 p.m.
[00:10:49 | 649s] And there are way more variations I
[00:10:50 | 650s] tested, too many to cover here, but just
[00:10:53 | 653s] know there's a lot more.
[00:10:55 | 655s] Those were the variables I tested, but
[00:10:57 | 657s] there were also some fixed settings I
[00:10:59 | 659s] used. Things like risk per trade,
[00:11:01 | 661s] slippage, and how I handled
[00:11:03 | 663s] over-fitting. I won't go through them in
[00:11:05 | 665s] detail, too. It'll take too long. If
[00:11:07 | 667s] you're curious, pause the video and read
[00:11:10 | 670s] through it. In total, I ended up testing
[00:11:12 | 672s] 90K combinations. For each asset, I
[00:11:16 | 676s] picked the best parameters, the ones
[00:11:18 | 678s] with the low drawdown and the highest
[00:11:20 | 680s] returns. And here's what I found.
[00:11:23 | 683s] The best combination was completely
[00:11:25 | 685s] different for each asset. For example,
[00:11:27 | 687s] this combination worked very well on
[00:11:29 | 689s] Euro, but the moment I applied the exact
[00:11:32 | 692s] parameters to ES, not that good. Look at
[00:11:35 | 695s] this.
[00:11:36 | 696s] So, here's the lesson. All those gurus
[00:11:39 | 699s] love to claim their exact setup works on
[00:11:41 | 701s] every asset. Now, you can see how
[00:11:43 | 703s] ridiculous that claim is.
[00:11:45 | 705s] If you've ever back-tested a single
[00:11:48 | 708s] strategy across multiple assets for any
[00:11:50 | 710s] decent length of time, you already know
[00:11:52 | 712s] this.
[00:11:53 | 713s] There's no such thing as one strategy
[00:11:55 | 715s] that works on everything because every
[00:11:58 | 718s] asset moves differently. Some trend
[00:12:00 | 720s] hard, some barely trend at all, some are
[00:12:03 | 723s] super volatile, some barely move. The
[00:12:06 | 726s] price action is just too different.
[00:12:08 | 728s] That's why you have to find the best
[00:12:10 | 730s] strategy for each asset.
[00:12:13 | 733s] Here are the equity curves for the best
[00:12:15 | 735s] parameters on each asset over the past 5
[00:12:18 | 738s] years. Blue line is ES equity curve,
[00:12:21 | 741s] orange line is NQ, green line is gold,
[00:12:24 | 744s] red line is euro. Let me walk you
[00:12:26 | 746s] through each one.
[00:12:27 | 747s] Starting with the euro, this was the
[00:12:29 | 749s] best-performing asset. The strategy
[00:12:32 | 752s] returned 630%
[00:12:34 | 754s] over 5 years with a clean upward trend.
[00:12:37 | 757s] Gold was the second best. Strong,
[00:12:40 | 760s] consistent growth, 431%
[00:12:42 | 762s] return over the same period. But ES and
[00:12:45 | 765s] NQ barely moved. ES returned only 77%
[00:12:50 | 770s] and NQ was even worse at just 71%. Both
[00:12:54 | 774s] were pretty much flat compared to the
[00:12:55 | 775s] other two.
[00:12:56 | 776s] And here's the key takeaway. On euro and
[00:12:59 | 779s] gold, the strategy worked great, but on
[00:13:02 | 782s] ES and NQ, even the best parameters I
[00:13:05 | 785s] could find couldn't beat just buy and
[00:13:06 | 786s] hold. So, if you're trading ES or NQ,
[00:13:09 | 789s] the 9:30 a.m. strategy isn't your
[00:13:12 | 792s] answer.
[00:13:13 | 793s] So, now you might be wondering, what
[00:13:15 | 795s] exactly made this strategy work on euro
[00:13:18 | 798s] and gold? What were the actual
[00:13:20 | 800s] parameters that produced these returns?
[00:13:23 | 803s] There were three key findings that
[00:13:25 | 805s] surprised me.
[00:13:27 | 807s] First, the basic 9:30 a.m. strategy
[00:13:30 | 810s] worked best and this was true for both
[00:13:32 | 812s] Euro and gold. No retest, no fair value
[00:13:35 | 815s] gap, no candlestick patterns, just a
[00:13:38 | 818s] limit order right after price breaks
[00:13:40 | 820s] out. That's it. Every guru claims you
[00:13:43 | 823s] need their secret to make this strategy
[00:13:45 | 825s] work. But the reality, those secrets
[00:13:48 | 828s] actually made it worse. The basic
[00:13:50 | 830s] version beat all of them.
[00:13:53 | 833s] Second, the risk-reward ratio. For both
[00:13:56 | 836s] Euro and gold, the best ratio was lower
[00:13:58 | 838s] than 1:2, so that always use 1:2 rule
[00:14:01 | 841s] every guru pushes, wrong.
[00:14:05 | 845s] Third, the time frame for defining the
[00:14:07 | 847s] range. Using the 5-minute candle wasn't
[00:14:09 | 849s] the best. A higher time frame like
[00:14:11 | 851s] 15-minute and 10-minute always worked
[00:14:14 | 854s] better. Time frame for entering was the
[00:14:16 | 856s] same. You should use time frame higher
[00:14:18 | 858s] than 1-minute or 5-minute.
[00:14:21 | 861s] Now, this was just the very rough
[00:14:23 | 863s] overview of what worked best. There are
[00:14:25 | 865s] a lot of more parameters I tested. For
[00:14:27 | 867s] those of you who want faster updates and
[00:14:29 | 869s] more detailed breakdowns, I created a
[00:14:31 | 871s] Telegram channel. The link is in the
[00:14:33 | 873s] description below and on my channel
[00:14:35 | 875s] page, come check it out. Most traders
[00:14:38 | 878s] don't even backtest their strategies.
[00:14:40 | 880s] They just jump straight into live
[00:14:42 | 882s] trading with a small account or if they
[00:14:44 | 884s] do backtest, they only do it for a month
[00:14:46 | 886s] or two on TradingView manually. But
[00:14:49 | 889s] after watching this video, I think you
[00:14:50 | 890s] can see how meaningless that is. A
[00:14:52 | 892s] 1-month or 2-month backtest tells you
[00:14:55 | 895s] almost nothing.
[00:14:57 | 897s] And not only that, most people don't
[00:14:59 | 899s] account for commissions or they overfit
[00:15:01 | 901s] their parameters or cherry-pick the best
[00:15:04 | 904s] period to look at.
[00:15:05 | 905s] There are so many ways to do it wrong.
[00:15:08 | 908s] The real problem, doing it properly
[00:15:10 | 910s] takes forever. Backtesting a single
[00:15:13 | 913s] strategy over long period of time using
[00:15:15 | 915s] hand takes weeks. And testing thousands
[00:15:18 | 918s] of combinations like I did, that's
[00:15:20 | 920s] basically impossible by
[00:15:23 | 923s] So, most people give up and just trust
[00:15:26 | 926s] whatever strategy they find on YouTube.
[00:15:28 | 928s] They lose months and thousands of
[00:15:30 | 930s] dollars on strategies that were never
[00:15:32 | 932s] properly verified. And then those gurus
[00:15:34 | 934s] blame you. They say things like, "You
[00:15:37 | 937s] need to find the right strategy for
[00:15:38 | 938s] you." Or even a good strategy fails
[00:15:41 | 941s] without a discipline.
[00:15:42 | 942s] As a systematic trader, I can tell you
[00:15:45 | 945s] that's nonsense.
[00:15:47 | 947s] I find this whole situation pretty sad,
[00:15:49 | 949s] and I want to help fix it. So, I'll be
[00:15:51 | 951s] sharing more videos, tools, and
[00:15:53 | 953s] resources to help you actually verify
[00:15:56 | 956s] strategies the right way.
[00:15:58 | 958s] If that sounds useful, hit subscribe so
[00:16:00 | 960s] you don't miss the next one. And if you
[00:16:02 | 962s] want to go deeper, check out my Telegram
[00:16:04 | 964s] channel and website. Links are in the
[00:16:06 | 966s] description.