import os
import psycopg2
from flask import Flask, render_template
import yfinance as yf
from urllib.parse import urlparse

app = Flask(__name__)

# Parse the database URL from the environment variable
db_url = urlparse(os.environ.get('DATABASE_URL'))

# Extract the connection details
db_host = db_url.hostname
db_name = db_url.path[1:]
db_user = db_url.username
db_password = db_url.password
db_port = db_url.port

# Function to update stock prices in the database
def update_stock_prices():
    symbols = {
        'GOOGL': 'Google',
        'META': 'Meta',
        'NFLX': 'Netflix',
        'NVDA': 'Nvidia',
        'MSFT': 'Microsoft',
        'TSLA': 'Tesla',
        'AMZN': 'Amazon'
    }  # Updated stock symbols and names
    
    # Connect to your PostgreSQL database using environment variables
    try:
        conn = psycopg2.connect(
            host=db_host,
            database=db_name,
            user=db_user,
            password=db_password,
            port=db_port
        )
        cursor = conn.cursor()
        
        for symbol, name in symbols.items():
            stock = yf.Ticker(symbol)
            price = stock.history(period='1d')['Close'].iloc[0]  # Get the latest closing price using iloc
            price = float(price)  # Ensure the price is a regular float type
            cursor.execute('UPDATE portfolio SET price = %s WHERE symbol = %s', (price, symbol))
            print(f"Updated {symbol}: {price}")  # Logging the update
        
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
            host=db_host,
            database=db_name,
            user=db_user,
            password=db_password,
            port=db_port
        )
        cursor = conn.cursor()
        cursor.execute('SELECT symbol, name, price FROM portfolio')
        portfolio = cursor.fetchall()
        print(portfolio)  # Debugging line
        cursor.close()
        conn.close()
        return render_template('index.html', portfolio=portfolio)
    except Exception as e:
        print(f"Error refreshing data: {e}")
        return render_template('index.html', error="Failed to refresh data")

if __name__ == "__main__":
    from os import environ
    app.run(host='0.0.0.0', port=int(environ.get('PORT', 5000)))
