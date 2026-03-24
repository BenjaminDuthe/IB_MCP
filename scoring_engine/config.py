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

# --- Telegram / Discord ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

# --- Alert threshold ---
SIGNAL_SCORE_THRESHOLD = int(os.environ.get("SIGNAL_SCORE_THRESHOLD", "4"))

# --- Feature flags ---
AGENT_LAYERS_ENABLED = os.environ.get("AGENT_LAYERS_ENABLED", "true").lower() == "true"
RISK_SIZING_ENABLED = os.environ.get("RISK_SIZING_ENABLED", "true").lower() == "true"
FEEDBACK_ENABLED = os.environ.get("FEEDBACK_ENABLED", "true").lower() == "true"

# --- Risk management ---
PORTFOLIO_VALUE = float(os.environ.get("PORTFOLIO_VALUE", "50000"))
MAX_POSITION_RISK_PCT = float(os.environ.get("MAX_POSITION_RISK_PCT", "2.0"))
MAX_SECTOR_EXPOSURE_PCT = float(os.environ.get("MAX_SECTOR_EXPOSURE_PCT", "40.0"))
DRAWDOWN_REDUCE_THRESHOLD = float(os.environ.get("DRAWDOWN_REDUCE_THRESHOLD", "5.0"))

# --- Performance tracking ---
WIN_RATE_DRIFT_THRESHOLD = float(os.environ.get("WIN_RATE_DRIFT_THRESHOLD", "0.60"))

# --- Ticker metadata (name, country, exchange) ---
TICKER_INFO = {
    # US Tech
    "NVDA":    {"name": "NVIDIA", "country": "🇺🇸", "exchange": "NASDAQ"},
    "MSFT":    {"name": "Microsoft", "country": "🇺🇸", "exchange": "NASDAQ"},
    "GOOGL":   {"name": "Alphabet (Google)", "country": "🇺🇸", "exchange": "NASDAQ"},
    "AMZN":    {"name": "Amazon", "country": "🇺🇸", "exchange": "NASDAQ"},
    "META":    {"name": "Meta Platforms", "country": "🇺🇸", "exchange": "NASDAQ"},
    "AAPL":    {"name": "Apple", "country": "🇺🇸", "exchange": "NASDAQ"},
    "NFLX":    {"name": "Netflix", "country": "🇺🇸", "exchange": "NASDAQ"},
    "TSLA":    {"name": "Tesla", "country": "🇺🇸", "exchange": "NASDAQ"},
    "AMD":     {"name": "Advanced Micro Devices", "country": "🇺🇸", "exchange": "NASDAQ"},
    "CRM":     {"name": "Salesforce", "country": "🇺🇸", "exchange": "NYSE"},
    "AVGO":    {"name": "Broadcom", "country": "🇺🇸", "exchange": "NASDAQ"},
    # US Healthcare
    "UNH":     {"name": "UnitedHealth Group", "country": "🇺🇸", "exchange": "NYSE"},
    "JNJ":     {"name": "Johnson & Johnson", "country": "🇺🇸", "exchange": "NYSE"},
    "LLY":     {"name": "Eli Lilly", "country": "🇺🇸", "exchange": "NYSE"},
    # US Finance
    "JPM":     {"name": "JPMorgan Chase", "country": "🇺🇸", "exchange": "NYSE"},
    "V":       {"name": "Visa", "country": "🇺🇸", "exchange": "NYSE"},
    # US Energy / Industrial
    "XOM":     {"name": "ExxonMobil", "country": "🇺🇸", "exchange": "NYSE"},
    "CAT":     {"name": "Caterpillar", "country": "🇺🇸", "exchange": "NYSE"},
    "BA":      {"name": "Boeing", "country": "🇺🇸", "exchange": "NYSE"},
    # US Consumer
    "COST":    {"name": "Costco", "country": "🇺🇸", "exchange": "NASDAQ"},
    "HD":      {"name": "Home Depot", "country": "🇺🇸", "exchange": "NYSE"},
    # France - Euronext Paris
    "MC.PA":   {"name": "LVMH", "country": "🇫🇷", "exchange": "Paris"},
    "SU.PA":   {"name": "Schneider Electric", "country": "🇫🇷", "exchange": "Paris"},
    "AIR.PA":  {"name": "Airbus", "country": "🇫🇷", "exchange": "Paris"},
    "BNP.PA":  {"name": "BNP Paribas", "country": "🇫🇷", "exchange": "Paris"},
    "SAF.PA":  {"name": "Safran", "country": "🇫🇷", "exchange": "Paris"},
    "TTE.PA":  {"name": "TotalEnergies", "country": "🇫🇷", "exchange": "Paris"},
    "OR.PA":   {"name": "L'Oréal", "country": "🇫🇷", "exchange": "Paris"},
    # Europe - Other
    "ASML.AS": {"name": "ASML Holding", "country": "🇳🇱", "exchange": "Amsterdam"},
    "SAP.DE":  {"name": "SAP", "country": "🇩🇪", "exchange": "Frankfurt"},
    "SIE.DE":  {"name": "Siemens", "country": "🇩🇪", "exchange": "Frankfurt"},
}

# --- Sector mapping ---
TICKER_SECTORS = {
    # US Tech
    "NVDA": "tech", "MSFT": "tech", "GOOGL": "tech", "AMZN": "tech",
    "META": "tech", "AAPL": "tech", "NFLX": "tech", "TSLA": "tech",
    "AMD": "tech", "CRM": "tech", "AVGO": "tech",
    # US Healthcare
    "UNH": "healthcare", "JNJ": "healthcare", "LLY": "healthcare",
    # US Finance
    "JPM": "finance", "V": "finance",
    # US Energy / Industrial
    "XOM": "energy", "CAT": "industrials", "BA": "aerospace",
    # US Consumer
    "COST": "consumer", "HD": "consumer",
    # EU
    "MC.PA": "luxury", "SU.PA": "materials", "AIR.PA": "industrials",
    "BNP.PA": "finance", "SAF.PA": "aerospace", "TTE.PA": "energy",
    "ASML.AS": "tech", "SAP.DE": "tech", "SIE.DE": "industrials",
    "OR.PA": "consumer",
}

# --- Watchlist ---
WATCHLIST = {
    # --- US Tech ---
    "NVDA":   {"market": "US", "t5d_threshold": 4.0, "rsi_threshold": 50, "require_sma200": False},
    "MSFT":   {"market": "US", "t5d_threshold": 1.5, "rsi_threshold": 55, "require_sma200": True},
    "GOOGL":  {"market": "US", "t5d_threshold": 3.0, "rsi_threshold": 50, "require_sma200": True},
    "AMZN":   {"market": "US", "t5d_threshold": 1.0, "rsi_threshold": 45, "require_sma200": False},
    "META":   {"market": "US", "t5d_threshold": 1.0, "rsi_threshold": 50, "require_sma200": True},
    "AAPL":   {"market": "US", "t5d_threshold": 3.5, "rsi_threshold": 50, "require_sma200": True},
    "NFLX":   {"market": "US", "t5d_threshold": 3.0, "rsi_threshold": 50, "require_sma200": True},
    "TSLA":   {"market": "US", "t5d_threshold": 5.0, "rsi_threshold": 50, "require_sma200": False},
    "AMD":    {"market": "US", "t5d_threshold": 4.0, "rsi_threshold": 50, "require_sma200": False},
    "CRM":    {"market": "US", "t5d_threshold": 2.0, "rsi_threshold": 55, "require_sma200": True},
    "AVGO":   {"market": "US", "t5d_threshold": 3.0, "rsi_threshold": 50, "require_sma200": True},
    # --- US Healthcare ---
    "UNH":    {"market": "US", "t5d_threshold": 2.0, "rsi_threshold": 55, "require_sma200": True},
    "JNJ":    {"market": "US", "t5d_threshold": 1.5, "rsi_threshold": 60, "require_sma200": True},
    "LLY":    {"market": "US", "t5d_threshold": 3.0, "rsi_threshold": 50, "require_sma200": True},
    # --- US Finance ---
    "JPM":    {"market": "US", "t5d_threshold": 2.0, "rsi_threshold": 55, "require_sma200": True},
    "V":      {"market": "US", "t5d_threshold": 1.5, "rsi_threshold": 55, "require_sma200": True},
    # --- US Energy / Industrial ---
    "XOM":    {"market": "US", "t5d_threshold": 3.0, "rsi_threshold": 55, "require_sma200": False},
    "CAT":    {"market": "US", "t5d_threshold": 2.5, "rsi_threshold": 55, "require_sma200": True},
    "BA":     {"market": "US", "t5d_threshold": 4.0, "rsi_threshold": 50, "require_sma200": False},
    # --- US Consumer ---
    "COST":   {"market": "US", "t5d_threshold": 1.5, "rsi_threshold": 55, "require_sma200": True},
    "HD":     {"market": "US", "t5d_threshold": 2.0, "rsi_threshold": 55, "require_sma200": True},
    # --- EU ---
    "MC.PA":  {"market": "FR", "t5d_threshold": 3.5, "rsi_threshold": 60, "require_sma200": False},
    "SU.PA":  {"market": "FR", "t5d_threshold": 4.0, "rsi_threshold": 55, "require_sma200": True},
    "AIR.PA": {"market": "FR", "t5d_threshold": 3.5, "rsi_threshold": 65, "require_sma200": False},
    "BNP.PA": {"market": "FR", "t5d_threshold": 2.5, "rsi_threshold": 50, "require_sma200": False},
    "SAF.PA": {"market": "FR", "t5d_threshold": 2.0, "rsi_threshold": 50, "require_sma200": True},
    "TTE.PA": {"market": "FR", "t5d_threshold": 3.5, "rsi_threshold": 55, "require_sma200": False},
    "ASML.AS": {"market": "FR", "t5d_threshold": 3.5, "rsi_threshold": 50, "require_sma200": True},
    "SAP.DE": {"market": "FR", "t5d_threshold": 2.0, "rsi_threshold": 55, "require_sma200": True},
    "SIE.DE": {"market": "FR", "t5d_threshold": 2.5, "rsi_threshold": 55, "require_sma200": True},
    "OR.PA":  {"market": "FR", "t5d_threshold": 2.0, "rsi_threshold": 55, "require_sma200": True},
}
