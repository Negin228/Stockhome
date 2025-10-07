# Stockhome

The goal:

Runs the code everyday at market open, highlights the "Buy"s. Runs every hour after that, and sends out notifications IF there are any changes and new tickers have been identified.

It checks the spot and strike prices as well as premiums for the identified tickers and calculates the following for different strike prices for the next 7 weeks:

  (Stop-Strike) + (premium)/100 = 0.1 * Stop (or more)

  Then suggests the Strike prices. 
  
S&P 500 list is a long one. Every night, do the following:
  Calculate RSI and P/E for the whole list.
  1) Prioritize as following: P/E <= 30 and RSI <= 30
  2) P/E > 30 and RSI <= 30 or  P/E <= 30 and RSI > 30 or P/E > 30 and RSI > 30
  3) Failed list due to limits

This list will be the input for Monday.

If the output of 1 shows any ticker with P/E <=30, it sends out an email. Then runs 2-5, and if there are more tickers, it will list them in a separate email. Aggregates all in a file, and runs the code every hour. This time, runs 1-5, and sends emails if there are any new tickers.

New Pro Metric:
delta ~0.20–0.30
Pick puts with 20–45 days left
Look for 1–2% of the stock price per month as your target.
Pro metric: (premium ÷ strike) × (30 ÷ DTE).
Only sell when IV Rank ≥ 40 (means options are expensive, so you’re paid better for the risk).
High IV = better premiums for you.
Skip stocks with earnings announcements in the next 7 days (price can jump or crash too much).

Take profits early: If you’ve earned 50–70% of the premium, close the trade early.
Roll at 21 DTE: If still open with no profit, “roll” it to next month’s promise.
Assignment = okay: You’re happy to own the stock at your strike price.

You’re basically the “insurance company.”
You only promise to buy strong, liquid stocks you’d be okay owning.
You either get free money or you get stocks at a discount.
Rinse, repeat.

Sell 20–45 DTE puts at ~0.20 delta, when IVR ≥ 40, avoid earnings, aim for 1–2% premium per month, take profit at 50–70%, roll losers, accept assignment only on stocks you love.

Check IV Rank ≥ 40
Pick 20–45 DTE
Choose ~0.20 delta strike
Avoid earnings ±7d
Collect premium
Then follow the management rules (close early, roll, or accept assignment).
