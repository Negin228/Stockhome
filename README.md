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


What to fix:
1) works if the file is not there, but then gives this error:
2025-08-20 00:36:38,872 [WARNING] Date parsing failed in cached data for CHTR, forcing full refresh
2) CSV files were not created when running on Github Actions
3) 6 or 7 weeks
4) PE --> p/E
5) highlight the strike prices where =~0.1
6) Can't rewrite the json files if they already exist
