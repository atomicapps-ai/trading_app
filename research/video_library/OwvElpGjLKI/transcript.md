# Transcript — OwvElpGjLKI
<https://www.youtube.com/watch?v=OwvElpGjLKI>

[00:00:00 | 0s] Have you ever thought to yourself, I wish
I could instantly test my strategy with out
[00:00:04 | 4s] waiting months or even years, to see if my
trading strategy is even good or not.
[00:00:09 | 9s] Well, what if I told you there s a way to
test any trading strategy you want on years
[00:00:14 | 14s] of data from the past, instantly. To see right
then and there if your trading strategy is
[00:00:19 | 19s] profitable or not.
Instead of just believing a YouTuber that
[00:00:23 | 23s] says they have a 100% win rate strategy, why
not test it for yourself to see if it really
[00:00:28 | 28s] is that good or not, and see how it compares
to your strategy that you re currently using.
[00:00:33 | 33s] In this video, I m going to show you exactly
how to do that. By backtesting your strategy
[00:00:37 | 37s] on TradingView with past years of data. So
you can see just how successful your trading
[00:00:43 | 43s] strategy really is.
Let s get straight to it.
[00:00:45 | 45s] First things first, we have to go to TradingView.
I ll have a link in the description. And as
[00:00:49 | 49s] a side note, this is completely free to use
and you don t need a paid subscription or
[00:00:53 | 53s] anything. Which is pretty awesome.
Once your on tradingview, go to chart option
[00:00:57 | 57s] on the top here.
Then type in any security you want to test
[00:01:01 | 61s] your strategy on. This will work with anything.
Stocks, forex, crypto, whatever.
[00:01:05 | 65s] For this example, I m going to test the Vanguard
S&P 500.
[00:01:09 | 69s] Now for this video we are going to test a
very simple trading strategy. Just so you
[00:01:13 | 73s] guys can kind of get a grasp on the basics
of backtesting. If this video gets a good
[00:01:17 | 77s] response and you guys really want to see more
of this, I ll do a 2nd video where I ll get
[00:01:21 | 81s] a little more advanced.
The trading strategy example we will do, is
[00:01:25 | 85s] just a simple moving average strategy.
It s pretty simple. We have a 20 day moving
[00:01:30 | 90s] average and a 50 day moving average. We want
to buy, when the 50 day crosses below the
[00:01:34 | 94s] 20 day, and we want to sell, when the 50 day
crosses above the 20 day.
[00:01:38 | 98s] Like I said, very basic and simple trading
strategy, but this is just to show you the
[00:01:42 | 102s] basics of backtesting.
I should also mention. That Tradingview has
[00:01:46 | 106s] a page where it has a bunch of pre bult in
variables functions, so you don t have to
[00:01:50 | 110s] custom make all of them. We are going to be
using a lot of them in this video. So I ll
[00:01:54 | 114s] leave that in the description as well if you
want to check that out.
[00:01:57 | 117s] So once you type in whatever security you
want to test. You are going to go down and
[00:02:01 | 121s] click on this bottom tab that says pine editor
.
[00:02:04 | 124s] The very first line, is what you want to name
your trading strategy. So, we are going to
[00:02:08 | 128s] name this simple moving average strategy .
Next, we are going to set our variables. The
[00:02:12 | 132s] first one we ll call ema20 for our 20 day
moving average and the second one we ll call
[00:02:17 | 137s] ema50 for our 50 day average.
Next we are going to use the built in ema
[00:02:22 | 142s] function from the tradingview page I was talking
about before. So we just type ema( . Now this
[00:02:28 | 148s] function takes two parameters. The first parameter
is if you want the ema to read from the open
[00:02:33 | 153s] or close of a candle as a reference point.
With moving averages, I think its best to
[00:02:37 | 157s] read from the close. So we ll do that for
this strategy.
[00:02:41 | 161s] Then the 2nd value is the time frame. So for
a 20 moving average we are going to set it
[00:02:45 | 165s] to 20.
Then you re going to do the exact same thing
[00:02:47 | 167s] for this one, but make it 50.
Next we are going to set our long and short
[00:03:02 | 182s] conditions.
So we want to go long, if ema20 is above the
[00:03:05 | 185s] ema50. Then we want to go short if the ema
20 is below ema50.
[00:03:11 | 191s] So keep in mind, these aren t entry points,
but they are just simply telling the bot what
[00:03:15 | 195s] we define as a long and what we think is a
short.
[00:03:19 | 199s] To do entry points we are going to use another
built in function, which is strategy.entry
[00:03:24 | 204s] .
The first parameter is the name, so we ll
[00:03:27 | 207s] call this entry long, then the 2nd parameter
is what we actually want to do, so we type
[00:03:32 | 212s] in strategy.long , the 3rd parameter is how
many shares you want to purchase, so in this
[00:03:37 | 217s] example we will just do 1000 shares.
Then the 4th parameter is when we want to
[00:03:42 | 222s] actually execute the trade, so we type when
= long . Which is saying we want to execute
[00:03:47 | 227s] a long trade when these parameters above are
met.
[00:03:51 | 231s] So we have the name, whether we want to go
long or short, the amount of shares, and when
[00:03:56 | 236s] want to execute.
Then we are going to do the same thin g for
[00:03:59 | 239s] a short trade. So name this short , strategy
we want is short, still have it as 1000 shares,
[00:04:05 | 245s] then we want it to execute it when this short
condition is true.
[00:04:08 | 248s] Right now we have it setup to where its longing
and shorting. But it s not actually closing
[00:04:13 | 253s] positions at this time. It s just constantly
opening trades.
[00:04:17 | 257s] So lets setup to where it actually closes
them.
[00:04:19 | 259s] To do that, just simply use strategy.close
. Then we are going to give it a few values
[00:04:24 | 264s] to tell the bot when we want to close a position.
So we want to reference what position we want
[00:04:28 | 268s] to close, so we want to close a long trade,
when short is true. Then we will do the opposite
[00:04:34 | 274s] for a short.
So close out a short position when long is
[00:04:38 | 278s] true.
So just all this code alone, in theory, will
[00:04:41 | 281s] buy every time when the 50 day crosses below
the 20 day, and will sell, when the 50 day
[00:04:46 | 286s] crosses above the 20 day.
It will also do the opposite with short trades.
[00:04:51 | 291s] Let s run it to see if it works.
To do that, go to this tab up here add to
[00:04:54 | 294s] chart and that will start our backtest.
So it looks like it worked. The cool thing
[00:04:59 | 299s] about tradingview, is that it will actually
display on the chart where it bought and sold.
[00:05:03 | 303s] This way you can check to see if the bot is
running correctly and buying and selling where
[00:05:07 | 307s] you actually want it to.
You also have these 3 different tabs.
[00:05:11 | 311s] The overview tab will show you an equity curve,
your net profit, amount of trades, max drawdown,
[00:05:16 | 316s] avg trade, etc.
The 
[00:05:25 | 325s] performance summary basically gives the same
information, but in a table format.
[00:05:30 | 330s] Then theres the list of trades tab, where
it will show you every single trade and when
[00:05:34 | 334s] and how it was executed. So you can see here,
that we went all the way back to the 1970s.
[00:05:38 | 338s] So maybe you don t want to test all the way
back to 1970? Well you can actually edit the
[00:05:43 | 343s] script to where you can tell the bot a specific
amount of time you want to test.
[00:05:47 | 347s] To do that, just go to this line right here
and create a start and end variable. Then
[00:05:51 | 351s] we are going to use the prebuilt timestamp
function So we are going to set our start,
[00:05:56 | 356s] lets say 2019, august, 1, then hours, and
minutes.
[00:06:01 | 361s] Then we ll just copy and paste this and set
our end point to 2020.
[00:06:06 | 366s] So this will test our strategy from august
2019 to august 2020 on the s&p 500.
[00:06:12 | 372s] Then we have to make an if statement. So if
time is greater than or equal to our start
[00:06:17 | 377s] variable and if time is less than or equal
to our end variable. We will run this code
[00:06:22 | 382s] below.
Then, you just indent this.
[00:06:25 | 385s] Go to the add to chart button, and boom, you
see that it tested trades from only 2019 to
[00:06:34 | 394s] 2020.
Now maybe you want to see your actually indicators
[00:06:44 | 404s] from the bot on the chart. Well, theres actually
a way to do that.
[00:06:48 | 408s] Theres a prebuilt function called the plot
function . So you just do plot( then whatever
[00:06:53 | 413s] indicator you want, the name, the color, then
the width.
[00:06:57 | 417s] Then boom, it shows you the moving averages
on the chart. Which is pretty cool.
[00:07:00 | 420s] B ut maybe you want it actually overlayed
on the chart as you normally would have it
[00:07:04 | 424s] when you add indicators.
To do that just go up here and set overlay
[00:07:08 | 428s] to true.
Then botta bing botta boom, you have the indicator
[00:07:11 | 431s] overlayed on the chart.
Like I said guys, this is a very basic strategy
[00:07:15 | 435s] and example, but I just wanted to show you
the very basic opportunities you have with
[00:07:20 | 440s] backtesting.
If you want to see a more advanced tutorial
[00:07:22 | 442s] on how to back test some advanced strategies,
like this video and let me know in the comments
[00:07:26 | 446s] if you want that, and I ll make a more advanced
tutorial.
[00:07:31 | 451s] Because there s some pretty crazy things you
can to with this tradingview backtesing.
[00:07:35 | 455s] Now that you know how to backtest, you should
backtest one of my strategies. Like this one,
[00:07:40 | 460s] where I show you one of my secret strategies
that has a high pretty high success rate.
[00:07:43 | 463s] Thanks for watching and I ll see you guys
next time.