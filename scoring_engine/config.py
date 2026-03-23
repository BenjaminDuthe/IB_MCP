"""Watchlist configuration and market hours."""

import os
from zoneinfo import ZoneInfo

# --- Market hours ---
TZ_CET = ZoneInfo("Europe/Paris")
TZ_ET = ZoneInfo("America/New_York")

EU_MARKET_OPEN = (9, 0)   # 09:00 CET
EU_MARKET_CLOSE = (17, 30) # 17:30 CET
US_MARKET_OPEN = (9, 30)   # 09:30 ET (15:30 CET)
US_MARKET_CLOSE = (16, 0)  # 16:00 ET (22:00 CET)

# --- Service URLs ---
MARKET_DATA_URL = os.environ.get("MCP_MARKET_DATA_URL", "http://mcp_market_data:5003")
SENTIMENT_URL = os.environ.get("MCP_SENTIMENT_URL", "http://mcp_sentiment:5004")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://192.168.1.120:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
INFLUXDB_URL = os.environ.get("INFLUXDB_URL", "http://192.168.1.123:8086")
INFLUXDB_DATABASE = os.environ.get("INFLUXDB_DATABASE", "trading")
INFLUXDB_USER = os.environ.get("INFLUXDB_USER", "trading_writer")
INFLUXDB_PASSWORD = os.environ.get("INFLUXDB_PASSWORD", "")
MONGODB_URI = os.environ.get("MONGODB_URI", "")

# --- Telegram / Discord ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

# --- Alert threshold ---
SIGNAL_SCORE_THRESHOLD = int(os.environ.get("SIGNAL_SCORE_THRESHOLD", "4"))

# --- Watchlist (from OpenClaw watchlist.json backtest v14) ---
WATCHLIST = {
    # US market
    "NVDA":   {"market": "US", "t5d_threshold": 4.0, "rsi_threshold": 50, "require_sma200": False},
    "MSFT":   {"market": "US", "t5d_threshold": 1.5, "rsi_threshold": 55, "require_sma200": True},
    "GOOGL":  {"market": "US", "t5d_threshold": 3.0, "rsi_threshold": 50, "require_sma200": True},
    "AMZN":   {"market": "US", "t5d_threshold": 1.0, "rsi_threshold": 45, "require_sma200": False},
    "META":   {"market": "US", "t5d_threshold": 1.0, "rsi_threshold": 50, "require_sma200": True},
    "AAPL":   {"market": "US", "t5d_threshold": 3.5, "rsi_threshold": 50, "require_sma200": True},
    "NFLX":   {"market": "US", "t5d_threshold": 3.0, "rsi_threshold": 50, "require_sma200": True},
    # EU market
    "MC.PA":  {"market": "FR", "t5d_threshold": 3.5, "rsi_threshold": 60, "require_sma200": False},
    "SU.PA":  {"market": "FR", "t5d_threshold": 4.0, "rsi_threshold": 55, "require_sma200": True},
    "AIR.PA": {"market": "FR", "t5d_threshold": 3.5, "rsi_threshold": 65, "require_sma200": False},
    "BNP.PA": {"market": "FR", "t5d_threshold": 2.5, "rsi_threshold": 50, "require_sma200": False},
    "SAF.PA": {"market": "FR", "t5d_threshold": 2.0, "rsi_threshold": 50, "require_sma200": True},
    "TTE.PA": {"market": "FR", "t5d_threshold": 3.5, "rsi_threshold": 55, "require_sma200": False},
}
