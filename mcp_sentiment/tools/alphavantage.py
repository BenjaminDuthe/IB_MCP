import os
import logging
import httpx
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sentiment", tags=["Alpha Vantage Sentiment"])

AV_BASE = "https://www.alphavantage.co/query"
CACHE_TTL_SECONDS = 14400  # 4h (only 25 calls/day — aggressive caching)
DAILY_LIMIT = 24  # buffer of 1

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; IB_MCP/1.0)",
    "Accept": "application/json",
}

_client = httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=20.0)

# Cache
_cache = {}

# Daily call counter (resets at midnight UTC)
_daily_counter = {"date": None, "count": 0}


def _get_cached(key: str) -> dict | None:
    if key in _cache:
        entry = _cache[key]
        if datetime.now() < entry["expires_at"]:
            return entry["data"]
        del _cache[key]
    return None


def _set_cache(key: str, data: dict) -> None:
    _cache[key] = {
        "data": data,
        "expires_at": datetime.now() + timedelta(seconds=CACHE_TTL_SECONDS),
    }


def _check_daily_limit() -> int:
    """Check and increment daily counter. Returns remaining calls, or -1 if limit reached."""
    today = datetime.now(timezone.utc).date()
    if _daily_counter["date"] != today:
        _daily_counter["date"] = today
        _daily_counter["count"] = 0

    if _daily_counter["count"] >= DAILY_LIMIT:
        return -1

    _daily_counter["count"] += 1
    return DAILY_LIMIT - _daily_counter["count"]


@router.get("/alphavantage/{ticker}")
async def get_alphavantage_sentiment(ticker: str):
    """Get Alpha Vantage news sentiment for a ticker. Free tier: 25 req/day, cached 1h."""
    api_key = os.environ.get("ALPHAVANTAGE_API_KEY")
    if not api_key or api_key.startswith("<"):
        raise HTTPException(status_code=503, detail="Alpha Vantage not configured. Set ALPHAVANTAGE_API_KEY.")

    cache_key = f"alphavantage_sentiment:{ticker.upper()}"
    cached = _get_cached(cache_key)
    if cached:
        return cached

    remaining = _check_daily_limit()
    if remaining < 0:
        raise HTTPException(
            status_code=429,
            detail=f"Alpha Vantage daily limit reached ({DAILY_LIMIT} calls). Resets at midnight UTC.",
        )

    try:
        resp = await _client.get(
            AV_BASE,
            params={
                "function": "NEWS_SENTIMENT",
                "tickers": ticker.upper(),
                "apikey": api_key,
            },
        )

        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Alpha Vantage returned {resp.status_code}")

        data = resp.json()

        if "Information" in data:
            raise HTTPException(status_code=429, detail=f"Alpha Vantage rate limit: {data['Information']}")

        feed = data.get("feed", [])
        if not feed:
            raise HTTPException(status_code=404, detail=f"No sentiment data for {ticker.upper()}")

        ticker_upper = ticker.upper()
        scores = []
        labels = []

        for article in feed:
            for ts in article.get("ticker_sentiment", []):
                if ts.get("ticker") == ticker_upper:
                    score = float(ts.get("ticker_sentiment_score", 0))
                    scores.append(score)
                    labels.append(ts.get("ticker_sentiment_label", "Neutral"))
                    break

        if not scores:
            raise HTTPException(status_code=404, detail=f"No ticker-specific sentiment for {ticker_upper}")

        avg_raw = sum(scores) / len(scores)
        # Alpha Vantage scores are already in -1..1 range (approximately -0.35 to 0.35 typical)
        # Normalize to fill -1..1 range better: clamp and scale
        sentiment_score = round(max(-1.0, min(1.0, avg_raw * 3)), 4)

        if sentiment_score > 0.1:
            unified_label = "bullish"
        elif sentiment_score < -0.1:
            unified_label = "bearish"
        else:
            unified_label = "neutral"

        result = {
            "ticker": ticker_upper,
            "source": "alphavantage",
            "sentiment_score": sentiment_score,
            "sentiment_label": unified_label,
            "raw_avg_score": round(avg_raw, 4),
            "article_count": len(scores),
            "daily_calls_remaining": remaining,
        }
        _set_cache(cache_key, result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Alpha Vantage error for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
