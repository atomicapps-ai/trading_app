# Transcript — sYRCzSbvOpQ
<https://www.youtube.com/watch?v=sYRCzSbvOpQ>

[00:00:00 | 0s] Total trades 697 and there was a win
[00:00:03 | 3s] rate of
[00:00:04 | 4s] 68.87% and the total profit was
[00:00:07 | 7s] $27,990. Instead of manually back
[00:00:09 | 9s] testing a trading strategy like this, I
[00:00:11 | 11s] back tested 21 plus years of market data
[00:00:14 | 14s] in about 6 seconds with the help of AI.
[00:00:16 | 16s] This changes everything for traders like
[00:00:18 | 18s] you and me because now we can back test
[00:00:20 | 20s] our trading strategies without knowing
[00:00:21 | 21s] how to code and we can optimize our
[00:00:23 | 23s] strategies faster than ever before.
[00:00:25 | 25s] How's it? My name is Hugh and in this
[00:00:27 | 27s] video I'll give you the exact steps that
[00:00:28 | 28s] you need to do your first back test with
[00:00:30 | 30s] Chat GPT. The best part is that this
[00:00:32 | 32s] entire process can be done totally for
[00:00:34 | 34s] free. Feel free to follow along so you
[00:00:36 | 36s] can see this in action for yourself and
[00:00:38 | 38s] rewind the video if you need to see one
[00:00:40 | 40s] of these steps again. While you're
[00:00:42 | 42s] watching this video, also keep in mind
[00:00:43 | 43s] that if you find a trading strategy that
[00:00:45 | 45s] you like, ChatGpt can help you turn that
[00:00:47 | 47s] into an automated robot or EA for
[00:00:50 | 50s] platforms like MetaTrader. But more on
[00:00:52 | 52s] that in future videos. Subscribe to the
[00:00:54 | 54s] channel if you want to be the first to
[00:00:55 | 55s] see those
[00:00:57 | 57s] videos. Now, you might be wondering, is
[00:00:59 | 59s] the back testing process really
[00:01:00 | 60s] necessary? Well, in my experience
[00:01:02 | 62s] working at a hedge fund and talking to
[00:01:04 | 64s] successful traders since 2007, I have
[00:01:06 | 66s] found that the only traders who become
[00:01:08 | 68s] successful are the ones who build and
[00:01:09 | 69s] test their own strategies. Period. No
[00:01:12 | 72s] exceptions. You can't just blindly
[00:01:13 | 73s] follow a trading strategy you learned on
[00:01:15 | 75s] the internet and expect to be
[00:01:16 | 76s] successful. You have to go through the
[00:01:18 | 78s] testing and verification process. But
[00:01:20 | 80s] the good news is that AI can help you
[00:01:22 | 82s] speed up things tremendously. The first
[00:01:24 | 84s] step to doing an AI back test is to get
[00:01:25 | 85s] some historical market data. You need to
[00:01:27 | 87s] have your own data because you need to
[00:01:29 | 89s] be sure that Chat GPT is doing the test
[00:01:31 | 91s] on a specific set of data and to verify
[00:01:34 | 94s] the results later. If you just ask
[00:01:36 | 96s] ChatGpt to randomly do a back test on a
[00:01:39 | 99s] market, you can't be sure where it's
[00:01:40 | 100s] getting the data from. Before I show you
[00:01:42 | 102s] how to do this, remember to be nice to
[00:01:44 | 104s] ChatGpt because when the AIs take over,
[00:01:46 | 106s] you probably want to be on their good
[00:01:48 | 108s] side. All right, let's get into it. The
[00:01:49 | 109s] first step is to download some free
[00:01:51 | 111s] historical market data. Now, you can get
[00:01:53 | 113s] free data for almost any market that you
[00:01:55 | 115s] want to back test, but MetaTrader makes
[00:01:57 | 117s] this super easy and it is free. So, I'm
[00:01:59 | 119s] going to use it in this example. Simply
[00:02:01 | 121s] download MetaTrader 4 or MetaTrader 5
[00:02:03 | 123s] and follow along. Once you've downloaded
[00:02:05 | 125s] and installed MetaTrader, set up a free
[00:02:07 | 127s] login that will give you a demo account
[00:02:09 | 129s] to try this out. Then go to tools and
[00:02:13 | 133s] then go to history center. Then look for
[00:02:16 | 136s] the market that you want to download. So
[00:02:17 | 137s] in this example, I'm going to use the
[00:02:18 | 138s] Euro US dollar since that's a very
[00:02:20 | 140s] frequently traded uh forex pair. So I'm
[00:02:24 | 144s] going to double click on Euro US dollar
[00:02:26 | 146s] and I'm going to do the daily chart
[00:02:28 | 148s] because the daily chart is easy to test.
[00:02:30 | 150s] Uh there isn't a ton of data, but you
[00:02:32 | 152s] can still create really good trading
[00:02:33 | 153s] strategies on that time frame. So double
[00:02:35 | 155s] click daily here and that will show you
[00:02:37 | 157s] all the database records that are
[00:02:39 | 159s] available. Right now I have
[00:02:41 | 161s] 1,961 records available. So, I'm going
[00:02:44 | 164s] to hit download to see if I can get more
[00:02:47 | 167s] data than what is already
[00:02:52 | 172s] available. It can take a little while
[00:02:54 | 174s] for the data to download depending on
[00:02:56 | 176s] your internet connection and the speed
[00:02:57 | 177s] of your computer. So, just be patient
[00:02:59 | 179s] and once that green bar goes across,
[00:03:01 | 181s] then you'll know that the process is
[00:03:03 | 183s] finished. Now, if you want to learn how
[00:03:04 | 184s] to speed up your computer, be sure to
[00:03:06 | 186s] check out my video on how to speed up a
[00:03:08 | 188s] trading computer and that could really
[00:03:10 | 190s] help you out. All right. So once the
[00:03:11 | 191s] data is downloaded, this is what it will
[00:03:13 | 193s] look like. Before we move on, I just
[00:03:14 | 194s] want to show you something really
[00:03:15 | 195s] quickly. If you scroll down on this
[00:03:18 | 198s] database window, you can see the first
[00:03:20 | 200s] date in the historical data. And for the
[00:03:22 | 202s] Euro US dollar daily chart, that's going
[00:03:25 | 205s] to be 1971. And I'll get to why this is
[00:03:27 | 207s] important in just a minute. Now, when
[00:03:28 | 208s] you're ready to export this free
[00:03:30 | 210s] historical data file, just hit the
[00:03:32 | 212s] export button, and that will give you
[00:03:34 | 214s] this CSV file with this file name. save
[00:03:36 | 216s] it somewhere where you can find it and
[00:03:38 | 218s] we'll use that for chat GPT to back test
[00:03:40 | 220s] on. Now I'm back at chat GPT and this is
[00:03:42 | 222s] where we start getting going. So if you
[00:03:45 | 225s] don't have an account yet, you can sign
[00:03:46 | 226s] up for a free one and the model that the
[00:03:48 | 228s] free account uses is chat
[00:03:51 | 231s] GPT40. So I'm going to select that one
[00:03:53 | 233s] just to show you that this can be done
[00:03:54 | 234s] in a free account. All right, I'm going
[00:03:56 | 236s] to start by
[00:03:57 | 237s] saying, hi, I would like to back
[00:04:02 | 242s] test some trading
[00:04:07 | 247s] strategies on a
[00:04:10 | 250s] historical data
[00:04:13 | 253s] file. Uh, is that
[00:04:17 | 257s] something you can help me with?
[00:04:21 | 261s] And this is important because you want
[00:04:23 | 263s] to give the AI some context. And if
[00:04:25 | 265s] you're using a different AI, it might
[00:04:27 | 267s] not be able to do this. So you should
[00:04:29 | 269s] you should ask if it is able to do this
[00:04:32 | 272s] first. So let's see what it
[00:04:33 | 273s] says. Okay. So it it's asking a few
[00:04:36 | 276s] questions here. And I'm just going to
[00:04:38 | 278s] upload the file. I'm not going to answer
[00:04:40 | 280s] all these questions. I'm just going to
[00:04:41 | 281s] upload the file and see if it can read
[00:04:43 | 283s] it. So to do that, I'm going to click on
[00:04:45 | 285s] the the plus button here, upload for
[00:04:47 | 287s] from computer, and upload that file that
[00:04:49 | 289s] I downloaded from MetaTrader. Open that
[00:04:52 | 292s] up right there. And as you can see,
[00:04:54 | 294s] that's attached. So I'm going to say
[00:04:57 | 297s] this is the file. So it says now it's
[00:05:01 | 301s] pre previewing the data and it shows you
[00:05:04 | 304s] all of the information that it has. And
[00:05:06 | 306s] it shows you that it recognizes uh this
[00:05:08 | 308s] format as the date, the time, open,
[00:05:11 | 311s] high, low, close, volume. So that's
[00:05:12 | 312s] perfect. That's exactly what we're
[00:05:14 | 314s] looking for. It also recognizes that
[00:05:16 | 316s] it's the daily chart because it's 100 uh
[00:05:18 | 318s] 1,440 minutes equals 1 day and it's the
[00:05:21 | 321s] Euro US dollar market. Perfect. Okay.
[00:05:23 | 323s] So, once it has this, now we can start
[00:05:25 | 325s] getting into back testing a strategy.
[00:05:27 | 327s] Now, if you remember from when we
[00:05:29 | 329s] downloaded the data in MetaTrader, the
[00:05:30 | 330s] data went back all the way to 1971 and
[00:05:33 | 333s] it identifies that there. So, I want to
[00:05:35 | 335s] tell ChatGBT not to use data that's
[00:05:38 | 338s] older than January 2003 because that's
[00:05:41 | 341s] when the Euro actually went into effect.
[00:05:44 | 344s] So, anything previous to that will be
[00:05:46 | 346s] data that we can't use. So, I'm going to
[00:05:49 | 349s] Oh, there's a little bit more data down
[00:05:51 | 351s] here. So, it says next step you can tell
[00:05:53 | 353s] me the rules for the entry, exit, take
[00:05:55 | 355s] profit. Perfect. Okay. So, it knows what
[00:05:57 | 357s] back testing is and it knows uh what
[00:06:00 | 360s] parameters it needs. So the first thing
[00:06:02 | 362s] I'm going to do before I get into the
[00:06:04 | 364s] entry and exit parameters is to tell it
[00:06:06 | 366s] to not use uh data before January 2003.
[00:06:11 | 371s] So
[00:06:12 | 372s] please only back test on data
[00:06:18 | 378s] uh after
[00:06:21 | 381s] uh from
[00:06:23 | 383s] January 2003
[00:06:27 | 387s] forward. See what it says.
[00:06:35 | 395s] So now it's cleaning up the data and uh
[00:06:40 | 400s] this is what it's showing. Okay,
[00:06:41 | 401s] perfect. So it starts on January 1st,
[00:06:44 | 404s] 2003 and it goes forward and if you
[00:06:46 | 406s] scroll down you can see that it goes all
[00:06:48 | 408s] the way to the current date of 2025. As
[00:06:51 | 411s] I go further down the page, it says the
[00:06:53 | 413s] data is now cleaned and it's asking for
[00:06:56 | 416s] the entry and exit rules. Okay. So, what
[00:06:59 | 419s] I want to do is I want to first identify
[00:07:02 | 422s] my trading strategy. So, if you have the
[00:07:04 | 424s] trading strategy worksheet that I have,
[00:07:07 | 427s] uh you can download that for free on my
[00:07:08 | 428s] website. Just uh search on my website
[00:07:10 | 430s] and you can find that and that will
[00:07:11 | 431s] allow you to uh put in all the
[00:07:13 | 433s] parameters that you need for a trading
[00:07:15 | 435s] strategy and that can really help you
[00:07:16 | 436s] organize your ideas. Or you can also
[00:07:18 | 438s] just go to a chart and put on the
[00:07:20 | 440s] indicators or whatever that you're using
[00:07:22 | 442s] and that will help you visualize the
[00:07:24 | 444s] trading strategy that you're trying to
[00:07:26 | 446s] develop because it can be kind of hard
[00:07:28 | 448s] to tell chat GPT just in words what the
[00:07:31 | 451s] trading strategy is. So I find it very
[00:07:33 | 453s] helpful to look at a chart first and
[00:07:35 | 455s] then kind of explain it to chat GPT uh
[00:07:37 | 457s] based on what's on the chart. Now for
[00:07:39 | 459s] this trading strategy, I had an idea
[00:07:41 | 461s] that I want to test out. So I wanted to
[00:07:43 | 463s] see how the 8 simple moving average and
[00:07:46 | 466s] the 25 simple moving average could be
[00:07:48 | 468s] used to create a trading strategy. So I
[00:07:50 | 470s] plotted it here. The blue is the 8 and
[00:07:53 | 473s] the gray is the 25. So my idea is what
[00:07:57 | 477s] if I bought when price closes below the
[00:08:02 | 482s] 8 simple moving average and then I
[00:08:04 | 484s] simply sell when it closes above the
[00:08:07 | 487s] eight simple moving average. And in
[00:08:09 | 489s] order to filter out signals, I would
[00:08:10 | 490s] only take buy trades if the eight is
[00:08:12 | 492s] above the 25. And I only take sell
[00:08:14 | 494s] trades when the eight is below the 25.
[00:08:17 | 497s] And for sell trades, I'm simply going to
[00:08:19 | 499s] sell when uh price is below the eight.
[00:08:22 | 502s] And I'll close out the trade when it
[00:08:24 | 504s] goes back above the eight. Now, I have
[00:08:25 | 505s] no idea if this is going to work. I'm
[00:08:27 | 507s] only making this up on the fly. And
[00:08:29 | 509s] that's a great part about this. You can
[00:08:30 | 510s] just think of an idea or you can take an
[00:08:32 | 512s] idea from a YouTube video or a blog post
[00:08:34 | 514s] and you can just test it out really
[00:08:36 | 516s] quickly. All right. Right now, I'll jump
[00:08:37 | 517s] back to chat GPT to do the test. But
[00:08:39 | 519s] before I move on, just really quick,
[00:08:40 | 520s] remember that chat GPT can make
[00:08:43 | 523s] mistakes. So, you always have to double
[00:08:45 | 525s] check the results you get from chat GPT.
[00:08:47 | 527s] I'll get to that more in future videos,
[00:08:49 | 529s] but this is just a great way to get a
[00:08:50 | 530s] quick initial back test and get some
[00:08:53 | 533s] data. Here's a big tip when entering
[00:08:54 | 534s] commands into chat GPT. I like to think
[00:08:56 | 536s] of it as a very smart employee. It can
[00:08:59 | 539s] do specific tasks extremely well, but it
[00:09:01 | 541s] lacks context as to the bigger picture.
[00:09:03 | 543s] So your job is to give it exact
[00:09:05 | 545s] instructions, double check its work, and
[00:09:08 | 548s] make sure that it's staying in line with
[00:09:10 | 550s] the vision that you're after. Explaining
[00:09:12 | 552s] what you want is especially important
[00:09:14 | 554s] because just like a human, it cannot
[00:09:15 | 555s] read your mind. So you have to give it
[00:09:17 | 557s] exact instructions. Also remember that
[00:09:20 | 560s] AI is not smarter than you. It just has
[00:09:21 | 561s] a different type of intelligence. So it
[00:09:23 | 563s] might be better than you at things like
[00:09:24 | 564s] programming and data analysis, but you
[00:09:27 | 567s] will be better at things like creativity
[00:09:28 | 568s] and coming up with new trading strategy
[00:09:30 | 570s] ideas. So when you work together,
[00:09:32 | 572s] amazing things can happen really quickly
[00:09:34 | 574s] and that's where the magic happens. All
[00:09:36 | 576s] right, back to the testing. So now I'm
[00:09:38 | 578s] going to explain to chat GPT the
[00:09:40 | 580s] strategy that I want to back test. So
[00:09:42 | 582s] I'm going to say I would like to back
[00:09:43 | 583s] test a trading
[00:09:47 | 587s] strategy that uses two simple
[00:09:53 | 593s] moving averages.
[00:09:57 | 597s] uh one is
[00:09:58 | 598s] [Music]
[00:10:00 | 600s] the 8 SMA and the other is the 25 SMA
[00:10:07 | 607s] and it will understand the SMA
[00:10:09 | 609s] abbreviation. Uh so you can go ahead and
[00:10:12 | 612s] use that. Uh if you're not sure if it
[00:10:14 | 614s] understands it or not, be sure to ask
[00:10:15 | 615s] and it will tell you. I would
[00:10:20 | 620s] like like to buy when price
[00:10:26 | 626s] closes below the 8
[00:10:32 | 632s] SMA and close the
[00:10:35 | 635s] trade
[00:10:37 | 637s] when price closes
[00:10:41 | 641s] above the
[00:10:44 | 644s] eight
[00:10:45 | 645s] SMA for a
[00:10:49 | 649s] cell. Oh, um I'll put in the 25 in there
[00:10:54 | 654s] right now. So, I'll say
[00:10:57 | 657s] um a buy can only open
[00:11:02 | 662s] if the 8 SMA is above the
[00:11:08 | 668s] 25
[00:11:11 | 671s] SMA. And then I can hit shift enter to
[00:11:14 | 674s] create a new line. uh and then I can see
[00:11:17 | 677s] for a sell
[00:11:19 | 679s] trade.
[00:11:21 | 681s] Uh first check to see that the 8 is
[00:11:29 | 689s] below the 25. I'm going to start
[00:11:32 | 692s] abbreviating here and see if it picks it
[00:11:34 | 694s] up.
[00:11:35 | 695s] Um then open a trade a
[00:11:40 | 700s] sell when price closes above the
[00:11:46 | 706s] eight. Uh closes below. Yeah. So above
[00:11:50 | 710s] the eight and
[00:11:52 | 712s] close the trade when
[00:11:56 | 716s] price closes below the
[00:12:00 | 720s] eight. Okay.
[00:12:02 | 722s] So, that's the strategy. Now, for
[00:12:05 | 725s] position size and everything, I'm just
[00:12:07 | 727s] going to keep it simple. So, I'm going
[00:12:09 | 729s] to say start with a
[00:12:13 | 733s] $10,000 account and
[00:12:17 | 737s] [Music]
[00:12:19 | 739s] enter.1
[00:12:21 | 741s] MetaTrader lots on each trade. So, it
[00:12:25 | 745s] should understand the uh MetaTrader
[00:12:27 | 747s] lots, but we'll see what happens. It has
[00:12:29 | 749s] in past back tests. So, let's see what
[00:12:32 | 752s] it comes up with. All right. So, then it
[00:12:33 | 753s] says, "Excellent, very clear." So, it's
[00:12:35 | 755s] going to repeat the parameters back to
[00:12:36 | 756s] me just to be sure that it has um
[00:12:38 | 758s] everything that I want. So, it's
[00:12:40 | 760s] building it now. And the back test is
[00:12:42 | 762s] complete. So, here's the summary. Total
[00:12:45 | 765s] trades 697 on the daily chart. And there
[00:12:49 | 769s] was a win rate of
[00:12:51 | 771s] 68.87% and the total profit was
[00:12:55 | 775s] $27,990. And the final account balance
[00:12:57 | 777s] was
[00:12:58 | 778s] $37,990. So, this is a profitable
[00:13:01 | 781s] trading strategy right off the bat. And
[00:13:03 | 783s] then if I go back to the calculation
[00:13:05 | 785s] time, it doesn't give it on this
[00:13:08 | 788s] version, but on the other version, the
[00:13:09 | 789s] paid version, it does show you how long
[00:13:11 | 791s] it took. And generally, these tests take
[00:13:13 | 793s] about 6 seconds uh in my experience. So,
[00:13:16 | 796s] this is super fast and it gives you
[00:13:18 | 798s] results right away. And if you look at
[00:13:20 | 800s] the table here, it shows you every
[00:13:21 | 801s] single trade in that back test. So, you
[00:13:24 | 804s] can verify this later on. And that's
[00:13:26 | 806s] fantastic. So it says now would you like
[00:13:29 | 809s] me to also plot a balance curve or
[00:13:31 | 811s] equity growth over time show a
[00:13:34 | 814s] distribution of trade profits and
[00:13:36 | 816s] calculate the maximum draw down or any
[00:13:38 | 818s] other metrics like the sharp ratio.
[00:13:39 | 819s] Fantastic. So yes it would be helpful to
[00:13:43 | 823s] uh take a look at some of these graphs
[00:13:44 | 824s] and some of these other metrics. So a
[00:13:46 | 826s] helpful thing to do would be to take a
[00:13:48 | 828s] look at the balance curve to see how
[00:13:50 | 830s] volatile this is. Right? So I'm going to
[00:13:52 | 832s] say yes please show me the balance
[00:13:56 | 836s] curve.
[00:13:58 | 838s] if I can spell correctly. Okay, so there
[00:14:01 | 841s] we go. Okay, so this is interesting. So
[00:14:03 | 843s] this trading strategy was profitable,
[00:14:06 | 846s] but it's not as profitable as it could
[00:14:08 | 848s] be because there was this big area here
[00:14:12 | 852s] where it went sidewards and then there
[00:14:13 | 853s] was a big draw down and then it battled
[00:14:15 | 855s] back. So there could be a lot of room
[00:14:16 | 856s] for optimization here even though this
[00:14:19 | 859s] strategy was profitable. Now let's take
[00:14:20 | 860s] a look at the maximum draw down. It's
[00:14:22 | 862s] asking about maximum draw down. So yes,
[00:14:24 | 864s] please show me the max draw down. Okay,
[00:14:27 | 867s] so the maximum draw down for this
[00:14:29 | 869s] strategy was
[00:14:30 | 870s] 67.63%. So that is a little rough. So
[00:14:33 | 873s] there is some room for optimization here
[00:14:35 | 875s] obviously because that's a very large
[00:14:37 | 877s] draw down as it says right there. So you
[00:14:40 | 880s] probably don't want to have that large
[00:14:41 | 881s] of a draw down. So one way we could
[00:14:43 | 883s] potentially limit the draw down on this
[00:14:45 | 885s] trading strategy is to use stop- losses.
[00:14:47 | 887s] I didn't use any stop losses because I
[00:14:49 | 889s] just wanted a quick and dirty test,
[00:14:50 | 890s] right? So, um, let's say I first need to
[00:14:54 | 894s] see the distribution of wins and losses,
[00:14:58 | 898s] and that could give me a clue as to
[00:14:59 | 899s] where the stop loss could be. Uh so I
[00:15:03 | 903s] I'm going to say
[00:15:05 | 905s] uh show me
[00:15:07 | 907s] the distri
[00:15:11 | 911s] distribution of losing trades as a
[00:15:18 | 918s] percentage of account
[00:15:21 | 921s] balances in a graph. Okay, so let's see
[00:15:26 | 926s] what it says. As you can see, uh, there
[00:15:29 | 929s] were a lot of really small losers and
[00:15:33 | 933s] then there are a few huge losers right
[00:15:35 | 935s] there. That's what's probably tanking
[00:15:37 | 937s] the account there. So, I could also show
[00:15:40 | 940s] this as uh a number of pips. So, uh,
[00:15:44 | 944s] please show me a graph of the losing
[00:15:50 | 950s] trades in pips. Okay, so some of the
[00:15:56 | 956s] trades went to 800 pips. Uh there were
[00:16:01 | 961s] some there's one that was a thousand.
[00:16:02 | 962s] That was the one that really tanked the
[00:16:03 | 963s] account. So a potential optimization
[00:16:06 | 966s] that you could do here possibly is to uh
[00:16:10 | 970s] maybe set a stop loss at 600 pips, like
[00:16:12 | 972s] a worst case scenario stop-loss, and see
[00:16:14 | 974s] how that goes. Uh, another thing you
[00:16:17 | 977s] could do is you could play with the
[00:16:20 | 980s] parameters of the moving averages a
[00:16:22 | 982s] little bit. Maybe you could have a 10
[00:16:24 | 984s] SMA instead of an eight and play with
[00:16:26 | 986s] those parameters a little bit. But just
[00:16:28 | 988s] for fun, let's try running the back test
[00:16:30 | 990s] again with a 600 pip stop
[00:16:33 | 993s] loss. So, I'm going to say thank you.
[00:16:36 | 996s] Please run the back test
[00:16:40 | 1000s] again, but add a 600 pip
[00:16:46 | 1006s] stop-loss on every
[00:16:49 | 1009s] trade and see how that does. So, it's
[00:16:52 | 1012s] going to run the analysis and we're
[00:16:54 | 1014s] going to see how this one potential
[00:16:56 | 1016s] optimization works. Sometimes it makes
[00:16:58 | 1018s] it worse, sometimes it makes it better.
[00:17:01 | 1021s] So, we won't know until we actually run
[00:17:03 | 1023s] the analysis. Okay, so this one took a
[00:17:05 | 1025s] little longer than 6 seconds, but it was
[00:17:06 | 1026s] still pretty quick. So, it's going to it
[00:17:09 | 1029s] shows all of the back test
[00:17:12 | 1032s] results and it says there were 699
[00:17:17 | 1037s] trades and the profit was actually less
[00:17:19 | 1039s] here. So, as you can see, a 600 pip
[00:17:21 | 1041s] stop-loss is not ideal and it actually
[00:17:23 | 1043s] lowers the profit and I would not have
[00:17:25 | 1045s] known that unless I did this back test.
[00:17:27 | 1047s] Now, chat GBT is very helpful and it
[00:17:30 | 1050s] gives a summary. Risk is much better
[00:17:34 | 1054s] controlled, but the profit is lower. And
[00:17:36 | 1056s] it gives some suggestions as to what I
[00:17:38 | 1058s] could possibly do next. Um, plot out the
[00:17:40 | 1060s] balance curve, calculate the maximum
[00:17:42 | 1062s] draw down, compare the two back tests
[00:17:44 | 1064s] visually. Uh, so let's take a look at
[00:17:46 | 1066s] that. I'm kind of curious. Um, please
[00:17:51 | 1071s] compare the two back
[00:17:54 | 1074s] tests visually. Okay, so as you can see
[00:18:00 | 1080s] uh with the 600 pip stop loss that's the
[00:18:03 | 1083s] dotted line uh that led to bigger draw
[00:18:06 | 1086s] downs and uh it was overall a worse
[00:18:08 | 1088s] strategy. So what's happening there is
[00:18:11 | 1091s] uh the stop loss was stopping out some
[00:18:13 | 1093s] winning trades also. So that's the
[00:18:15 | 1095s] reason why it performed worse. So as you
[00:18:18 | 1098s] can see this is a really quick way to
[00:18:20 | 1100s] start back testing strategies. uh you
[00:18:23 | 1103s] can test whatever idea you can come up
[00:18:25 | 1105s] with and you can see the results right
[00:18:28 | 1108s] away. Now, here's a very important tip
[00:18:30 | 1110s] when it comes to back testing. Always
[00:18:32 | 1112s] make sure that you keep one trading
[00:18:34 | 1114s] strategy per chat. So, that allows you
[00:18:37 | 1117s] to go back into your old chats and maybe
[00:18:40 | 1120s] play with some ideas that you had before
[00:18:43 | 1123s] without confusing the AI by putting two
[00:18:45 | 1125s] different trading strategies in the same
[00:18:47 | 1127s] chat. So if you are done with this and
[00:18:50 | 1130s] you're like h maybe I want to try
[00:18:51 | 1131s] something else. Then just go into
[00:18:53 | 1133s] another chat, hit chat GPT again. It'll
[00:18:56 | 1136s] bring up another chat and that will be
[00:18:58 | 1138s] available in your history. So you can
[00:18:59 | 1139s] start playing with a new trading
[00:19:00 | 1140s] strategy idea and then save this one and
[00:19:03 | 1143s] then maybe go back to the other one if
[00:19:05 | 1145s] you want to test some other markets.
[00:19:06 | 1146s] Maybe you want to test the pound dollar
[00:19:08 | 1148s] or the US the US or you want to change
[00:19:11 | 1151s] some of the parameters. You want to play
[00:19:12 | 1152s] with the moving averages. Maybe you want
[00:19:14 | 1154s] to add in an RSI or another indicator or
[00:19:16 | 1156s] something like that. Then that would be
[00:19:18 | 1158s] a great way to keep all of your tests
[00:19:21 | 1161s] separate and allow you to come back to
[00:19:23 | 1163s] them later. All right, now I'm back in
[00:19:25 | 1165s] the original back test and uh let's see
[00:19:27 | 1167s] what chat GPT would suggest in terms of
[00:19:30 | 1170s] how to improve this. All right. So,
[00:19:32 | 1172s] um, what
[00:19:35 | 1175s] are some
[00:19:38 | 1178s] suggestions for
[00:19:41 | 1181s] making
[00:19:43 | 1183s] this
[00:19:46 | 1186s] strategy more
[00:19:50 | 1190s] profitable and less
[00:19:54 | 1194s] volatile? Okay, so it's giving me a good
[00:19:56 | 1196s] summary of the strategy, why it's good,
[00:19:59 | 1199s] why it's not good.
[00:20:00 | 1200s] And here are some suggestions. So it's
[00:20:02 | 1202s] giving me five strategic suggestions to
[00:20:04 | 1204s] increase the profitability and reduce
[00:20:07 | 1207s] volatility. So it says add a minimum
[00:20:10 | 1210s] price distance filter for entry. Don't
[00:20:12 | 1212s] immediately enter when price
[00:20:14 | 1214s] crosses. Only enter a minimum distance
[00:20:17 | 1217s] away 10 to 20 pips
[00:20:19 | 1219s] that result. This avoids noise that
[00:20:22 | 1222s] barely uh crosses the SMA. Uh use a
[00:20:26 | 1226s] takerit in addition to a stop-loss. A
[00:20:29 | 1229s] dynamic takeprofit would massively
[00:20:32 | 1232s] improve
[00:20:33 | 1233s] the profit
[00:20:35 | 1235s] factor. Okay, so for example, if 600
[00:20:38 | 1238s] pips, um you're looking for a 600 or 900
[00:20:41 | 1241s] pip
[00:20:43 | 1243s] uh take
[00:20:45 | 1245s] profit. Uh this can also increase the
[00:20:47 | 1247s] win rate. Okay. Uh tighten the stop loss
[00:20:50 | 1250s] adaptively. You can use an ATR based
[00:20:53 | 1253s] stop-loss. Add a timebased
[00:20:56 | 1256s] exit. Okay. and confirm trades with a
[00:21:00 | 1260s] trend filter. Okay, that that generally
[00:21:03 | 1263s] doesn't work too well, so I'm not going
[00:21:04 | 1264s] to do that one. Um, so there are some
[00:21:08 | 1268s] different ideas here, some good ideas
[00:21:10 | 1270s] that can be used to possibly improve
[00:21:12 | 1272s] this. So, let's see. I am going to hm
[00:21:16 | 1276s] what would be the best one to use here?
[00:21:18 | 1278s] I I want to try out uh I'm not too
[00:21:22 | 1282s] interested in that first one. Let's try
[00:21:25 | 1285s] the Let's try the
[00:21:26 | 1286s] takerit. Um, let's try using a
[00:21:32 | 1292s] 600
[00:21:34 | 1294s] pip stop
[00:21:37 | 1297s] loss. Let's try a 400 pip and see what
[00:21:39 | 1299s] happens. A 400 pip stop loss and
[00:21:44 | 1304s] a 800
[00:21:47 | 1307s] pip take profit. Okay. So, it's going to
[00:21:50 | 1310s] reiterate what I uh the instructions
[00:21:53 | 1313s] that I gave it. So, uh that looks good.
[00:21:57 | 1317s] That looks good. Okay. So, now it's
[00:21:59 | 1319s] running it with the 400 pip stop loss
[00:22:02 | 1322s] and the 800 pip take profit. And we'll
[00:22:05 | 1325s] see how this goes. I don't uh I don't
[00:22:07 | 1327s] think this is going to do very well, but
[00:22:09 | 1329s] that's why we test. And it was slightly
[00:22:11 | 1331s] more profitable. Interesting. And the
[00:22:13 | 1333s] the win rate was about the same. And
[00:22:14 | 1334s] there were more trades here. So, uh,
[00:22:17 | 1337s] let's scroll down to take a look at some
[00:22:19 | 1339s] of the analysis. Higher total profit,
[00:22:22 | 1342s] still maintains a very high win rate,
[00:22:25 | 1345s] likely smoother and catastrophic
[00:22:28 | 1348s] drawdowns. Um, let's take a look at the
[00:22:31 | 1351s] balance curve again. Yes,
[00:22:34 | 1354s] please plot the new balance curve. All
[00:22:38 | 1358s] right, so the new balance curve looks
[00:22:40 | 1360s] pretty much similar to the last one that
[00:22:42 | 1362s] I did. So, this isn't a big improvement.
[00:22:44 | 1364s] However, it is a step in the right
[00:22:46 | 1366s] direction. So, I can start playing with
[00:22:47 | 1367s] some of these ideas like the stop-loss
[00:22:49 | 1369s] takeprofit and then I can go back to
[00:22:51 | 1371s] some of these other ideas that chat GPT
[00:22:53 | 1373s] suggested or I can come up with my own
[00:22:56 | 1376s] ideas as to how to improve this strategy
[00:22:58 | 1378s] a little bit more. In future videos, I'm
[00:23:00 | 1380s] going to be showing you how to take
[00:23:01 | 1381s] these ideas that you back tested and
[00:23:03 | 1383s] verified and turn them into actual
[00:23:05 | 1385s] trading robots that can either automate
[00:23:08 | 1388s] your entire trading strategy or you can
[00:23:10 | 1390s] automate parts of the strategy like the
[00:23:12 | 1392s] open or the trade management or just the
[00:23:14 | 1394s] close. And that can save you a lot of
[00:23:16 | 1396s] time and that can add a lot of profits
[00:23:18 | 1398s] to your bottom line. So, be sure to
[00:23:19 | 1399s] subscribe if you want to get those
[00:23:21 | 1401s] videos and check out the video that's
[00:23:22 | 1402s] coming up next.