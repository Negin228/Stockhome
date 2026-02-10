import json
import requests
from datetime import datetime
import os
import html

# Telegram Configuration - read from environment variables
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# File paths
SPREADS_FILE = "data/spreads.json"
PREVIOUS_TICKERS_FILE = "data/previous_tickers.json"
LAST_SUMMARY_FILE = "data/last_summary_date.json"  # NEW

def escape_html(text):
    """Escape HTML special characters for Telegram"""
    if text is None:
        return ""
    return html.escape(str(text))

def send_telegram_message(message):
    """Send a message via Telegram bot"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("✗ Telegram credentials not configured")
        return False
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    
    try:
        response = requests.post(url, json=payload)
        if not response.ok:
            print(f"✗ Telegram API error: {response.status_code}")
            print(f"Response: {response.text}")
        response.raise_for_status()
        print(f"✓ Message sent successfully")
        return True
    except Exception as e:
        print(f"✗ Failed to send message: {e}")
        return False

def format_spread_info(spread):
    """Format a single spread for display"""
    ticker = escape_html(spread.get('ticker', 'N/A'))
    strategy = escape_html(spread.get('strategy', 'N/A'))
    price = spread.get('price', 'N/A')
    reasoning = escape_html(spread.get('reasoning', 'No reasoning available'))
    
    # Truncate reasoning if too long
    if len(reasoning) > 200:
        reasoning = reasoning[:197] + "..."
    
    # Format price safely
    price_str = f"${price:.0f}" if isinstance(price, (int, float)) else str(price)
    
    return f"<b>{ticker}</b> ({price_str})\n{strategy}\n{reasoning}\n"

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
    os.makedirs(os.path.dirname(PREVIOUS_TICKERS_FILE) if os.path.dirname(PREVIOUS_TICKERS_FILE) else ".", exist_ok=True)
    with open(PREVIOUS_TICKERS_FILE, 'w') as f:
        json.dump(list(tickers), f)

def get_last_summary_date():
    """Get the date of the last daily summary"""
    try:
        with open(LAST_SUMMARY_FILE, 'r') as f:
            data = json.load(f)
            return data.get('date')
    except (FileNotFoundError, json.JSONDecodeError):
        return None

def save_summary_date(date_str):
    """Save the date of today's summary"""
    os.makedirs(os.path.dirname(LAST_SUMMARY_FILE) if os.path.dirname(LAST_SUMMARY_FILE) else ".", exist_ok=True)
    with open(LAST_SUMMARY_FILE, 'w') as f:
        json.dump({'date': date_str}, f)

def send_daily_bullish_summary():
    """Send daily summary of all bullish spreads (once per day only)"""
    today = datetime.now().strftime('%Y-%m-%d')
    last_summary = get_last_summary_date()
    
    # Check if we already sent summary today
    if last_summary == today:
        print(f"Daily summary already sent today ({today}). Skipping.")
        return
    
    spreads = load_spreads()
    
    # Filter for bullish spreads only
    bullish_spreads = [
        s for s in spreads 
        if 'bull' in s.get('strategy', '').lower()
    ]
    
    if not bullish_spreads:
        message = "📊 <b>Daily Bullish Spreads Summary</b>\n\n"
        message += "No bullish spread candidates today."
        if send_telegram_message(message):
            save_summary_date(today)
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
    if current_message and send_telegram_message(current_message):
        save_summary_date(today)
        print(f"✓ Sent daily summary with {count} bullish spreads")

def send_new_ticker_alerts():
    """Send alert for any new tickers not in previous run"""
    spreads = load_spreads()
    previous_tickers = load_previous_tickers()
    current_tickers = {s.get('ticker') for s in spreads if s.get('ticker')}
    
    # Save current state for next run FIRST
    save_current_tickers(current_tickers)
    
    # Find new tickers
    new_tickers = current_tickers - previous_tickers
    
    # Don't send alert if this is the first run (no previous data)
    if not previous_tickers:
        print(f"First run detected. Initialized with {len(current_tickers)} tickers. No alert sent.")
        return
    
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

def main():
    """Main function to run both notifications"""
    print("Starting Telegram notifications...")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Send daily bullish summary (once per day)
    print("\n--- Sending Daily Summary ---")
    send_daily_bullish_summary()
    
    # Send new ticker alerts (every run)
    print("\n--- Checking for New Tickers ---")
    send_new_ticker_alerts()
    
    print("\n✓ All notifications complete!")

if __name__ == "__main__":
    main()
