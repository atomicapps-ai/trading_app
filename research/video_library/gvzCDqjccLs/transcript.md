# Transcript — gvzCDqjccLs
<https://www.youtube.com/watch?v=gvzCDqjccLs>

[00:00:00 | 0s] today i'm going to demonstrate a way to
[00:00:01 | 1s] improve an already profitable
[00:00:03 | 3s] trading strategy that was originally
[00:00:05 | 5s] created
[00:00:06 | 6s] and documented by larry connors and
[00:00:09 | 9s] cesar alvarez the modification i'm going
[00:00:11 | 11s] to show you is dead simple
[00:00:12 | 12s] and it triples the net profit it
[00:00:15 | 15s] increases the winning percentage to over
[00:00:17 | 17s] 90 percent
[00:00:18 | 18s] and it reduces the drawdown too those of
[00:00:20 | 20s] you who are regular viewers to the
[00:00:21 | 21s] channel
[00:00:22 | 22s] may remember a similar study i did a
[00:00:24 | 24s] while ago
[00:00:25 | 25s] however this time i put a different
[00:00:27 | 27s] twist on the exit to get different
[00:00:28 | 28s] results the strategy uses
[00:00:30 | 30s] the relative strength index or rsi
[00:00:33 | 33s] indicator
[00:00:34 | 34s] to get signals off of a daily chart and
[00:00:37 | 37s] it works on the s
[00:00:38 | 38s] p 500 this is going to be probably a
[00:00:40 | 40s] shorter than normal video for me
[00:00:42 | 42s] because the modification is so simple so
[00:00:46 | 46s] i'm going to show you how to get into
[00:00:47 | 47s] the trades then we go over the
[00:00:48 | 48s] modification
[00:00:49 | 49s] and compare the results i'm going to
[00:00:51 | 51s] show you the test results using the spx
[00:00:54 | 54s] cfd contract supplied by oanda
[00:00:57 | 57s] and that tracks the e-mini future very
[00:00:59 | 59s] well the results you'll see
[00:01:01 | 61s] are going to be in points rather than
[00:01:03 | 63s] dollars because
[00:01:05 | 65s] the point value for the cfd is actually
[00:01:07 | 67s] slightly different to the point value of
[00:01:09 | 69s] the e-mini or the micro e-mini for the
[00:01:12 | 72s] main test we're going to be looking at
[00:01:13 | 73s] data from 2008
[00:01:14 | 74s] through to the end of 2019 then we're
[00:01:16 | 76s] going to run some optimizations
[00:01:18 | 78s] and make some modifications and then
[00:01:20 | 80s] look at the rest of the data i have
[00:01:22 | 82s] which is from
[00:01:23 | 83s] 2020 through to the end of june 2021.
[00:01:26 | 86s] let's look at the rules as i've already
[00:01:28 | 88s] mentioned we're looking at
[00:01:30 | 90s] the s p 500 and we're looking at a daily
[00:01:33 | 93s] chart
[00:01:34 | 94s] we're going to be using the rsi
[00:01:35 | 95s] indicator and we're going to set it
[00:01:37 | 97s] to a period of two so we're looking at a
[00:01:39 | 99s] very short period
[00:01:41 | 101s] rsi the general idea of the strategy
[00:01:44 | 104s] is we're looking at an overall uptrend
[00:01:46 | 106s] so it's a long only strategy we're only
[00:01:48 | 108s] looking for buy trades
[00:01:50 | 110s] and we're only looking for buys when the
[00:01:52 | 112s] closing price
[00:01:54 | 114s] or the closing daily price of the s p is
[00:01:56 | 116s] above its 200 period moving average
[00:01:59 | 119s] you can use a simple moving average or
[00:02:01 | 121s] an exponential it doesn't make much
[00:02:03 | 123s] difference
[00:02:03 | 123s] in my test i just happen to be using a
[00:02:05 | 125s] simple moving average
[00:02:06 | 126s] once we've seen that the closing price
[00:02:08 | 128s] is above that 200 period moving average
[00:02:11 | 131s] we're assuming that we're in an overall
[00:02:13 | 133s] uptrend an overall bull market
[00:02:15 | 135s] and then we're looking at very
[00:02:17 | 137s] short-term drops in price
[00:02:19 | 139s] or pullbacks and we want to buy those
[00:02:21 | 141s] pullbacks or buy those dips
[00:02:23 | 143s] and then wait for prices to then turn
[00:02:25 | 145s] around and begin to rally again
[00:02:28 | 148s] and then we take our profit into those
[00:02:30 | 150s] rallies and we use the rsi indicator
[00:02:33 | 153s] to identify those short-term pullbacks
[00:02:35 | 155s] we use our two-period rsi
[00:02:37 | 157s] and we look for the rsi to cross down
[00:02:41 | 161s] below
[00:02:41 | 161s] the 10 level we can set these levels on
[00:02:44 | 164s] our charts i think the standard is
[00:02:45 | 165s] usually 30
[00:02:47 | 167s] but we're going to use a lower level of
[00:02:49 | 169s] 10 so
[00:02:50 | 170s] when it crosses below 10 then we buy
[00:02:53 | 173s] on the next open larry connors does talk
[00:02:55 | 175s] about using a level of 5
[00:02:57 | 177s] rather than 10. however with 5 you are
[00:03:00 | 180s] going to get less trades so
[00:03:02 | 182s] for this test i'm going to use 10. larry
[00:03:04 | 184s] connors also doesn't document a stop
[00:03:06 | 186s] loss
[00:03:07 | 187s] he's discovered that in this sort of a
[00:03:09 | 189s] mean reversion type strategy
[00:03:11 | 191s] that stop losses do just hurt the
[00:03:12 | 192s] performance however
[00:03:14 | 194s] i like to trade with the stop-loss i'm
[00:03:15 | 195s] sure you like to trade in the loss
[00:03:17 | 197s] so i've actually done a quick test and
[00:03:20 | 200s] worked out that a 200 point stop loss
[00:03:23 | 203s] works quite well
[00:03:24 | 204s] 200 is quite large but we want to give
[00:03:27 | 207s] the
[00:03:27 | 207s] prices room to continue to go down ever
[00:03:30 | 210s] so slightly before they they go back up
[00:03:32 | 212s] so 200 is quite a nice area so that's
[00:03:35 | 215s] what we're using for this study
[00:03:36 | 216s] larry connors also suggests a few
[00:03:38 | 218s] different exits and they all work
[00:03:40 | 220s] some of the exits that he suggests is
[00:03:43 | 223s] putting a five-period moving average on
[00:03:46 | 226s] the price and exiting
[00:03:47 | 227s] when the daily price closes above that
[00:03:50 | 230s] five period moving average
[00:03:52 | 232s] a ten period works as well and he also
[00:03:55 | 235s] suggests one using the rsi indicator
[00:03:57 | 237s] so for this study i'm going to use the
[00:03:59 | 239s] rsi indicator
[00:04:00 | 240s] and our exit what we're going to compare
[00:04:03 | 243s] to is
[00:04:04 | 244s] exiting when value of the rsi closes
[00:04:08 | 248s] above the 70 level okay so 10 is our
[00:04:11 | 251s] entry
[00:04:12 | 252s] and then 70 is going to be our exit
[00:04:14 | 254s] level or
[00:04:15 | 255s] that's going to be what we're comparing
[00:04:16 | 256s] it to i'm going to introduce a slightly
[00:04:18 | 258s] different exit
[00:04:19 | 259s] but for the baseline that's our
[00:04:21 | 261s] comparison using that 70 level
[00:04:23 | 263s] because as with using a level of 10 or 5
[00:04:27 | 267s] for the entry
[00:04:28 | 268s] the exit there is no perfect one some
[00:04:30 | 270s] work better in some cases
[00:04:32 | 272s] somewhat better in other cases and
[00:04:34 | 274s] that's the baseline strategy that i'm
[00:04:35 | 275s] going to compare it to
[00:04:37 | 277s] when i do the modification i'm going to
[00:04:38 | 278s] keep the entry identical
[00:04:40 | 280s] i'm just going to modify the exit and
[00:04:42 | 282s] for that i'm going to use
[00:04:44 | 284s] a method that i picked up from larry
[00:04:45 | 285s] williams which i've used quite a lot on
[00:04:47 | 287s] this channel
[00:04:48 | 288s] which is his bad out exit or first
[00:04:50 | 290s] profitable close
[00:04:52 | 292s] and what that means is we look at the
[00:04:53 | 293s] closing price of each day and if we're
[00:04:56 | 296s] in profit
[00:04:56 | 296s] we get out and take the profit if we're
[00:04:58 | 298s] not in profit we leave the trade open
[00:05:01 | 301s] and it'll either hit the stop loss or we
[00:05:04 | 304s] will take the profit
[00:05:05 | 305s] so let's go to the computer and have a
[00:05:06 | 306s] look how the modification to the exit
[00:05:09 | 309s] works or improves over this baseline one
[00:05:12 | 312s] that we're going to compare to
[00:05:13 | 313s] in this first workspace i've got two
[00:05:15 | 315s] charts
[00:05:16 | 316s] and the top chart or the top pane uses
[00:05:20 | 320s] the strategy that uses the rsi for the
[00:05:23 | 323s] exit
[00:05:23 | 323s] so whenever the rsi crosses over
[00:05:26 | 326s] 70 we exit and the bottom one
[00:05:30 | 330s] down here it uses the first profitable
[00:05:33 | 333s] close
[00:05:34 | 334s] a closing price of every bar if we're in
[00:05:36 | 336s] profit we just exit the trade
[00:05:38 | 338s] and you'll notice that in the bottom we
[00:05:40 | 340s] have got a few more trades because
[00:05:43 | 343s] we're exiting a little bit quicker so
[00:05:44 | 344s] the entry in fact let me just
[00:05:47 | 347s] put the rsi so you can see what the
[00:05:49 | 349s] entry is
[00:05:52 | 352s] we use the two period rsi and we're
[00:05:55 | 355s] looking at
[00:05:57 | 357s] an oversold level of 10 and we leave the
[00:05:59 | 359s] overbought level which is our exit as
[00:06:01 | 361s] 70.
[00:06:04 | 364s] so we can see
[00:06:09 | 369s] every time so this green line here this
[00:06:11 | 371s] bottom line is the 10 level
[00:06:13 | 373s] so the minute the rsi comes below
[00:06:17 | 377s] 10 we've got a buy and then we're not
[00:06:19 | 379s] exiting
[00:06:20 | 380s] until it goes above 70 here and we're
[00:06:23 | 383s] exiting on the next bar
[00:06:25 | 385s] so again below 10. didn't get above 70
[00:06:28 | 388s] so we stayed in the trade went below 10
[00:06:30 | 390s] again but we stayed in the original
[00:06:32 | 392s] trade
[00:06:32 | 392s] exited above 70. so
[00:06:35 | 395s] that's the original one and
[00:06:39 | 399s] on the bottom one it's just exiting
[00:06:41 | 401s] first profitable close
[00:06:42 | 402s] so let's have a look at the results the
[00:06:44 | 404s] first one
[00:06:48 | 408s] there's the equity curve and it's not
[00:06:50 | 410s] bad again
[00:06:51 | 411s] data from 2008 through to the end of
[00:06:53 | 413s] 2019
[00:06:55 | 415s] recently has dropped off a little bit
[00:07:01 | 421s] make a net profit of 731 points
[00:07:08 | 428s] 76 trades we've got a percent profitable
[00:07:11 | 431s] or win rate of just over
[00:07:12 | 432s] 81 an average trade of
[00:07:16 | 436s] 9.6 points per trade
[00:07:19 | 439s] so let's compare that to the first
[00:07:22 | 442s] profitable close
[00:07:25 | 445s] firstly here's the equity curve
[00:07:29 | 449s] similar probably not quite as good
[00:07:34 | 454s] making less net profit at only 588
[00:07:37 | 457s] points this time
[00:07:40 | 460s] a few more trades 79
[00:07:43 | 463s] the winning percentage is higher the
[00:07:45 | 465s] average trade is slightly lower
[00:07:47 | 467s] only 7.4 points per trade
[00:07:51 | 471s] notice we got our largest losing trade
[00:07:53 | 473s] of 200 that's our 200 point stop loss
[00:07:56 | 476s] so that's the comparison between the
[00:07:58 | 478s] baseline using the rsi exit
[00:08:00 | 480s] and the first profitable close before i
[00:08:04 | 484s] make any modifications
[00:08:05 | 485s] in the previous video i made which was
[00:08:08 | 488s] using a similar exit using the
[00:08:10 | 490s] first profitable close what i looked at
[00:08:12 | 492s] was the amount of points we were in
[00:08:14 | 494s] profit
[00:08:15 | 495s] before exiting at the moment in this
[00:08:18 | 498s] study
[00:08:18 | 498s] we're looking are we in profit or not in
[00:08:21 | 501s] profit
[00:08:22 | 502s] so even if at the end of the day we're
[00:08:24 | 504s] two points in profit we exit the trade
[00:08:27 | 507s] in the previous video i looked to see if
[00:08:29 | 509s] there was a better number than just
[00:08:31 | 511s] 1.2 points etc which done on
[00:08:34 | 514s] optimization and i found that 30 worked
[00:08:36 | 516s] quite well
[00:08:37 | 517s] so we were looking for a minimum of 30
[00:08:40 | 520s] points
[00:08:40 | 520s] now in this video in this study what
[00:08:43 | 523s] we're going to look at next
[00:08:44 | 524s] is leaving the the points in profit
[00:08:47 | 527s] at anything above zero so it could be
[00:08:49 | 529s] just one point in profit
[00:08:51 | 531s] however i am going to introduce a delay
[00:08:54 | 534s] on
[00:08:54 | 534s] that exit so what i'm going to say is i
[00:08:56 | 536s] want to be in the trade for
[00:08:58 | 538s] a minimum amount of time before we
[00:09:01 | 541s] employ that exit
[00:09:02 | 542s] so it might be the case that we want to
[00:09:05 | 545s] enter the trade we want to be in the
[00:09:06 | 546s] trade at least three days
[00:09:08 | 548s] and then only after that third day we
[00:09:11 | 551s] look at
[00:09:12 | 552s] each end of day are we in profit if
[00:09:14 | 554s] we're in profit
[00:09:15 | 555s] it could be a couple of points it could
[00:09:17 | 557s] be 30 points we take the profit
[00:09:19 | 559s] and run but we're using that day delay
[00:09:22 | 562s] that's what we're going to look at next
[00:09:23 | 563s] we're going to look at an optimization
[00:09:25 | 565s] to see if the day delay
[00:09:27 | 567s] improves the results and i'm sure it
[00:09:29 | 569s] will so in this workspace
[00:09:31 | 571s] we're looking at the day delay and i'll
[00:09:34 | 574s] show you the optimization report
[00:09:36 | 576s] and you see i've created this input
[00:09:38 | 578s] called day delay
[00:09:40 | 580s] one is no delay whatsoever you'll
[00:09:42 | 582s] remember our 588
[00:09:44 | 584s] points profit has 79 trades and i've
[00:09:48 | 588s] looked at
[00:09:49 | 589s] right way through to 20 days i don't
[00:09:51 | 591s] want to be in the trade
[00:09:52 | 592s] much more than 20 days this is a short
[00:09:54 | 594s] term trading strategy now looking down
[00:09:57 | 597s] the net profit and the average trade
[00:09:59 | 599s] value
[00:10:00 | 600s] we can quite quickly see that there's
[00:10:02 | 602s] some decent
[00:10:17 | 617s] and we still got a really high percent
[00:10:19 | 619s] profitable as well we've kept
[00:10:20 | 620s] over 91 profitable which is good so the
[00:10:23 | 623s] rules would be
[00:10:24 | 624s] enter the trade wait 12 days and then
[00:10:27 | 627s] start looking
[00:10:28 | 628s] every day are we in profit if we are in
[00:10:30 | 630s] profit we exit
[00:10:32 | 632s] if we're not in profit we stay in the
[00:10:33 | 633s] trade and
[00:10:35 | 635s] we've got an increased net profit an
[00:10:37 | 637s] increased
[00:10:38 | 638s] average trade very slightly increased
[00:10:41 | 641s] profitability or win rate and
[00:10:44 | 644s] let's have a look at the drawdown draw
[00:10:46 | 646s] down -270 points compared to -327
[00:10:51 | 651s] using no delay at all so it looks better
[00:10:55 | 655s] all round in my opinion so let's use
[00:10:58 | 658s] that one
[00:10:58 | 658s] and look at the equity curve
[00:11:05 | 665s] so that's the equity curve which i think
[00:11:07 | 667s] you'll agree is better
[00:11:10 | 670s] recently we are making new highs so
[00:11:12 | 672s] that's good
[00:11:13 | 673s] we've already seen the the net profit
[00:11:16 | 676s] over 2
[00:11:17 | 677s] 100 points now so that's over triple the
[00:11:19 | 679s] amount of our baseline study
[00:11:21 | 681s] using the rsi 70 as the exit if you
[00:11:24 | 684s] remember the rsi
[00:11:25 | 685s] exit only made 731 points
[00:11:29 | 689s] so that's really good and max drawdown
[00:11:32 | 692s] for this strategy
[00:11:33 | 693s] is 270 points and the max drawdown for
[00:11:37 | 697s] the rsi exit was 281 points so
[00:11:42 | 702s] slightly less drawdown using this exit
[00:11:45 | 705s] 2.
[00:11:45 | 705s] looking at the total trade analysis we
[00:11:47 | 707s] have got less trades
[00:11:48 | 708s] the rsrx it had 76 trades now we've only
[00:11:51 | 711s] got 60 with this
[00:11:53 | 713s] because we're staying in the trade
[00:11:54 | 714s] longer giving us a higher chance of
[00:11:56 | 716s] making bigger profit
[00:11:58 | 718s] percent profitable we've already seen
[00:12:00 | 720s] just over 91
[00:12:01 | 721s] the rsi exit was only 81.5
[00:12:05 | 725s] the average trade here is huge at 35.7
[00:12:09 | 729s] points compared to
[00:12:10 | 730s] using the rsi exit of only 9.6 points
[00:12:14 | 734s] and the largest losing trade on both of
[00:12:17 | 737s] them is 200 because that's our 200 point
[00:12:20 | 740s] stop loss so i think you'll agree that
[00:12:22 | 742s] we've got improvements
[00:12:23 | 743s] all around using this exits the last
[00:12:26 | 746s] thing we do
[00:12:27 | 747s] in this pane we've got both the
[00:12:28 | 748s] strategies we've got
[00:12:30 | 750s] the top one which is using 70 level of
[00:12:32 | 752s] the rsi
[00:12:34 | 754s] and the bottom one which is using the
[00:12:36 | 756s] first profit will close with the 12-day
[00:12:39 | 759s] delay
[00:12:39 | 759s] and i want to look at the results from
[00:12:42 | 762s] 2020
[00:12:43 | 763s] through to the end of june 2021.
[00:12:46 | 766s] let's first look at the equity curves of
[00:12:48 | 768s] both so
[00:12:49 | 769s] one we're using the rsi exit
[00:12:52 | 772s] i've actually included the whole data
[00:12:54 | 774s] but i've just added on
[00:12:56 | 776s] the extra unseen data and the equity
[00:12:58 | 778s] curve is not great within the last few
[00:13:01 | 781s] years unfortunately
[00:13:02 | 782s] let's compare that to using the first
[00:13:05 | 785s] profitable close with the day delay
[00:13:08 | 788s] and we're actually making new highs the
[00:13:10 | 790s] equity curve is still a little bit
[00:13:12 | 792s] choppy like the other one
[00:13:13 | 793s] but we are making new highs you can see
[00:13:16 | 796s] here
[00:13:16 | 796s] making new highs let's look at the
[00:13:18 | 798s] periodic analysis
[00:13:20 | 800s] and that will show us how much profit
[00:13:22 | 802s] each strategy has made
[00:13:24 | 804s] so we've got 2021 so we've only got six
[00:13:27 | 807s] months of 2021
[00:13:29 | 809s] so far and all of 2020. so remember
[00:13:32 | 812s] we're looking at the strategy
[00:13:34 | 814s] now using the first profitable close
[00:13:36 | 816s] with the day delay
[00:13:38 | 818s] so we made 303.8 in 2021.
[00:13:42 | 822s] we lost 137.7 in 2020
[00:13:46 | 826s] for a grand total of about
[00:13:49 | 829s] 166 points let's have a look at the
[00:13:54 | 834s] rsi exit
[00:13:58 | 838s] and 2021 we made 165
[00:14:01 | 841s] lost 117 for a grand total of
[00:14:06 | 846s] only 48 points so in the out of sample
[00:14:09 | 849s] data
[00:14:10 | 850s] the exit using the first profitable
[00:14:12 | 852s] close and the 12-day delay
[00:14:14 | 854s] did work better well i told you today's
[00:14:17 | 857s] video was going to be a slightly shorter
[00:14:19 | 859s] one
[00:14:20 | 860s] in this demonstration what i've shown is
[00:14:22 | 862s] that the entry and the exit rules
[00:14:24 | 864s] of a certain strategy don't have to be
[00:14:26 | 866s] set in stone
[00:14:28 | 868s] as long as we're using the the main idea
[00:14:31 | 871s] and the main idea in this strategy being
[00:14:33 | 873s] we're looking for an overall
[00:14:35 | 875s] uptrend or a longer-term uptrend and
[00:14:37 | 877s] we're looking at a way to
[00:14:38 | 878s] identify very short-term pullbacks
[00:14:41 | 881s] buying into those pullbacks and then
[00:14:43 | 883s] exiting into strength or once we're in
[00:14:46 | 886s] profit and i've demonstrated that
[00:14:47 | 887s] different exit ideas
[00:14:49 | 889s] do work and i've also demonstrated that
[00:14:52 | 892s] the longer we're in a trade the more
[00:14:54 | 894s] chance we have of catching a bigger move
[00:14:57 | 897s] and getting a more quality trade that's
[00:14:59 | 899s] why using the 12-day delay
[00:15:01 | 901s] works really well if you're already
[00:15:03 | 903s] trading this strategy of
[00:15:04 | 904s] larry connors then you might want to
[00:15:07 | 907s] consider using
[00:15:08 | 908s] this version too something i often do
[00:15:11 | 911s] when
[00:15:12 | 912s] i get a strategy and two different exits
[00:15:14 | 914s] do work
[00:15:15 | 915s] then sometimes i split my positions into
[00:15:17 | 917s] half let's say you're
[00:15:18 | 918s] trading 10 contracts trade five
[00:15:21 | 921s] contracts using
[00:15:22 | 922s] your original or your preferred exit
[00:15:24 | 924s] technique and trade the other five
[00:15:26 | 926s] contracts
[00:15:26 | 926s] using the different technique like this
[00:15:28 | 928s] one and that's
[00:15:30 | 930s] quite a good way to work things it's
[00:15:31 | 931s] quite a good way of diversifying the two
[00:15:33 | 933s] strategies
[00:15:35 | 935s] within the same strategy so i hope
[00:15:36 | 936s] you've enjoyed this video
[00:15:38 | 938s] if you have please give it a thumbs up
[00:15:40 | 940s] and until the next one
[00:15:41 | 941s] this is jared goodwin and thank you