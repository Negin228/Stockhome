import os
import numpy as np
import psycopg2
from flask import Flask, render_template, jsonify
import yfinance as yf

# Check if DB_HOST is set
db_host = os.environ.get('DB_HOST')
if db_host is None:
    print("DB_HOST is not set")

app = Flask(__name__)

# Function to update stock prices in the database
def update_stock_prices():
    symbols = ['GOOGL', 'META', 'NFLX', 'NVDA', 'MSFT', 'TSLA', 'AMZN']  # Updated stock symbols
    
    # Connect to your PostgreSQL database using environment variables
    try:
        conn = psycopg2.connect(
            host=db_host,
            database=os.environ['DB_NAME'],
            user=os.environ['DB_USER'],
            password=os.environ['DB_PASSWORD']
        )
        cursor = conn.cursor()
        
        for symbol in symbols:
            stock = yf.Ticker(symbol)
            price = stock.history(period='1d')['Close'][0]  # Get the latest closing price
            price = float(price)  # Ensure the price is a regular float type
            cursor.execute('UPDATE portfolio SET price = %s WHERE symbol = %s', (price, symbol))
        
        conn.commit()
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error updating stock prices: {e}")

@app.route('/')
def home():
    try:
        update_stock_prices()
        # Fetch the updated stock data from the database
        conn = psycopg2.connect(
            host=os.environ['DB_HOST'],
            database=os.environ['DB_NAME'],
            user=os.environ['DB_USER'],
            password=os.environ['DB_PASSWORD']
        )
        cursor = conn.cursor()
        cursor.execute('SELECT symbol, name, price FROM portfolio')
        portfolio = cursor.fetchall()
        cursor.close()
        conn.close()
        return render_template('index.html', portfolio=portfolio)
    except Exception as e:
        print(f"Error refreshing data: {e}")
        return render_template('index.html', error="Failed to refresh data")

if __name__ == "__main__":
    from os import environ
    app.run(host='0.0.0.0', port=int(environ.get('PORT', 5000)))
