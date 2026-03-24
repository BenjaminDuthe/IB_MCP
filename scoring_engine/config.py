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

# --- Feature flags (gradual rollout) ---
AGENT_LAYERS_ENABLED = os.environ.get("AGENT_LAYERS_ENABLED", "false").lower() == "true"
DEBATE_ENABLED = os.environ.get("DEBATE_ENABLED", "false").lower() == "true"
RISK_SIZING_ENABLED = os.environ.get("RISK_SIZING_ENABLED", "false").lower() == "true"
FEEDBACK_ENABLED = os.environ.get("FEEDBACK_ENABLED", "false").lower() == "true"

# --- Analyst weights in composite score ---
ANALYST_WEIGHTS = {
    "technical": float(os.environ.get("WEIGHT_TECHNICAL", "0.40")),
    "fundamental": float(os.environ.get("WEIGHT_FUNDAMENTAL", "0.25")),
    "sentiment": float(os.environ.get("WEIGHT_SENTIMENT", "0.20")),
    "macro": float(os.environ.get("WEIGHT_MACRO", "0.15")),
}

# --- Debate config ---
DEBATE_MAX_TOKENS = int(os.environ.get("DEBATE_MAX_TOKENS", "200"))
DEBATE_TEMPERATURE = float(os.environ.get("DEBATE_TEMPERATURE", "0.4"))

# --- Risk management ---
PORTFOLIO_VALUE = float(os.environ.get("PORTFOLIO_VALUE", "50000"))
MAX_POSITION_RISK_PCT = float(os.environ.get("MAX_POSITION_RISK_PCT", "2.0"))
MAX_SECTOR_EXPOSURE_PCT = float(os.environ.get("MAX_SECTOR_EXPOSURE_PCT", "40.0"))
DRAWDOWN_REDUCE_THRESHOLD = float(os.environ.get("DRAWDOWN_REDUCE_THRESHOLD", "5.0"))

# --- Performance tracking ---
WIN_RATE_DRIFT_THRESHOLD = float(os.environ.get("WIN_RATE_DRIFT_THRESHOLD", "0.60"))

# --- Sector mapping ---
TICKER_SECTORS = {
    "NVDA": "tech", "MSFT": "tech", "GOOGL": "tech", "AMZN": "tech",
    "META": "tech", "AAPL": "tech", "NFLX": "tech",
    "MC.PA": "luxury", "SU.PA": "materials", "AIR.PA": "industrials",
    "BNP.PA": "finance", "SAF.PA": "aerospace", "TTE.PA": "energy",
}

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
