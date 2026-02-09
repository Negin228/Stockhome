import json
import requests
from datetime import datetime
import os

# Telegram Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")  # Get from @BotFather
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")      # Get from @userinfobot

# File paths
SPREADS_FILE = "data/spreads.json"
PREVIOUS_TICKERS_FILE = "data/previous_tickers.json"

def send_telegram_message(message):
    """Send a message via Telegram bot"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print(f"✓ Message sent successfully")
        return True
    except Exception as e:
        print(f"✗ Failed to send message: {e}")
        return False

def format_spread_info(spread):
    """Format a single spread for display"""
    ticker = spread.get('ticker', 'N/A')
    strategy = spread.get('strategy', 'N/A')
    price = spread.get('price', 'N/A')
    reasoning = spread.get('reasoning', 'No reasoning available')
    
    # Truncate reasoning if too long
    if len(reasoning) > 200:
        reasoning = reasoning[:197] + "..."
    
    return f"<b>{ticker}</b> (${price:.0f})\n{strategy}\n{reasoning}\n"

def load_spreads():
    """Load current spreads data"""
    try:
        with open(SPREADS_FILE, 'r') as f:
            data = json.load(f)
            if isinstance(data, dict) and 'data' in data:
                return data['data']
            return data if isinstance(data, list) else []
    except FileNotFoundError:
        print(f"✗ Spreads file not found: {SPREADS_FILE}")
        return []
    except json.JSONDecodeError as e:
        print(f"✗ Error parsing spreads file: {e}")
        return []

def load_previous_tickers():
    """Load previous run's ticker list"""
    try:
        with open(PREVIOUS_TICKERS_FILE, 'r') as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def save_current_tickers(tickers):
    """Save current ticker list for next run"""
    with open(PREVIOUS_TICKERS_FILE, 'w') as f:
        json.dump(list(tickers), f)

def send_daily_bullish_summary():
    """Send daily summary of all bullish spreads"""
    spreads = load_spreads()
    
    # Filter for bullish spreads only
    bullish_spreads = [
        s for s in spreads 
        if 'bull' in s.get('strategy', '').lower()
    ]
    
    if not bullish_spreads:
        message = "📊 <b>Daily Bullish Spreads Summary</b>\n\n"
        message += "No bullish spread candidates today."
        send_telegram_message(message)
        return
    
    # Split into chunks if too many (Telegram has 4096 char limit)
    message = f"📊 <b>Daily Bullish Spreads Summary</b>\n"
    message += f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M PT')}\n"
    message += f"Total: {len(bullish_spreads)} bullish spreads\n\n"
    
    current_message = message
    count = 0
    
    for spread in bullish_spreads:
        spread_text = format_spread_info(spread)
        
        # Check if adding this would exceed Telegram's limit
        if len(current_message + spread_text) > 4000:
            send_telegram_message(current_message)
            current_message = f"📊 <b>Daily Bullish Spreads (continued)</b>\n\n"
        
        current_message += spread_text + "\n"
        count += 1
    
    # Send final message
    if current_message:
        send_telegram_message(current_message)
    
    print(f"✓ Sent daily summary with {count} bullish spreads")

def send_new_ticker_alerts():
    """Send alert for any new tickers not in previous run"""
    spreads = load_spreads()
    previous_tickers = load_previous_tickers()
    current_tickers = {s.get('ticker') for s in spreads if s.get('ticker')}
    
    # Find new tickers
    new_tickers = current_tickers - previous_tickers
    
    if new_tickers:
        new_spreads = [s for s in spreads if s.get('ticker') in new_tickers]
        
        message = f"🆕 <b>NEW SPREAD CANDIDATES</b>\n"
        message += f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M PT')}\n"
        message += f"Found {len(new_tickers)} new ticker(s)!\n\n"
        
        for spread in new_spreads:
            message += format_spread_info(spread) + "\n"
        
        send_telegram_message(message)
        print(f"✓ Sent alert for {len(new_tickers)} new tickers: {new_tickers}")
    else:
        print("No new tickers to alert")
    
    # Save current tickers for next run
    save_current_tickers(current_tickers)

def main():
    """Main function to run both notifications"""
    print("Starting Telegram notifications...")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Send daily bullish summary
    print("\n--- Sending Daily Summary ---")
    send_daily_bullish_summary()
    
    # Send new ticker alerts
    print("\n--- Checking for New Tickers ---")
    send_new_ticker_alerts()
    
    print("\n✓ All notifications complete!")

if __name__ == "__main__":
    main()
