# Stockhome

The goal:

Runs the code everyday at market open, highlights the "Buy"s. Runs every hour after that, and sends out notifications IF there are any changes and new tickers have been identified.

It checks the spot and strike prices as well as premiums for the identified tickers and calculates the following for different strike prices for the next 7 weeks:

  (Stop-Strike) + (premium)/100 = 0.1 * Stop (or more)

  Then suggests the Strike prices. 
  
