import os   # <-- ADD this line!

# Email / SMTP settings
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587

# Technical indicator thresholds
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
MA_SHORT = 50
MA_LONG = 200

# Data storage & cache settings
DATA_DIR = "data"
MAX_CACHE_AGE_DAYS = 30   # force full refresh if cache older than this

# Logging settings
LOG_DIR = "logs"
LOG_FILE = "signal.log"
LOG_MAX_BYTES = 1_000_000   # 1 MB per log file
LOG_BACKUP_COUNT = 5        # keep up to 5 rotated log files

# CSV alerts log
ALERTS_CSV = os.path.join(LOG_DIR, "alerts_history.csv")
