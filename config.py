# config.py

# Email / SMTP settings
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587

# Technical indicator thresholds
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
MA_SHORT = 50
MA_LONG = 200

# Data storage + cache settings
DATA_DIR = "data"
MAX_CACHE_AGE_DAYS = 30   # after this, do a full refresh
