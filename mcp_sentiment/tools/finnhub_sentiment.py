import asyncio
import os
import logging
import finnhub
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sentiment", tags=["Finnhub News Sentiment"])

# In-memory cache (TTL: 5 minutes)
_cache = {}
CACHE_TTL_SECONDS = 300

_finnhub_client = None


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


def _get_finnhub_client():
    global _finnhub_client
    if _finnhub_client is None:
        api_key = os.environ.get("FINNHUB_API_KEY")
        if not api_key:
            return None
        _finnhub_client = finnhub.Client(api_key=api_key)
    return _finnhub_client


@router.get("/finnhub/{ticker}")
async def get_finnhub_sentiment(ticker: str):
    """Get Finnhub news sentiment for a ticker: NLP-based bullish/bearish scores from press articles."""
    cache_key = f"finnhub_sentiment:{ticker.upper()}"
    cached = _get_cached(cache_key)
    if cached:
        return cached

    client = _get_finnhub_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Finnhub API not configured. Set FINNHUB_API_KEY.")

    try:
        data = await asyncio.to_thread(client.news_sentiment, ticker.upper())

        if not data or not data.get("sentiment"):
            raise HTTPException(status_code=404, detail=f"No sentiment data for {ticker.upper()}")

        sentiment = data["sentiment"]
        buzz = data.get("buzz", {})

        bullish_pct = sentiment.get("bullishPercent", 0)
        bearish_pct = sentiment.get("bearishPercent", 0)
        sentiment_score = round(bullish_pct - bearish_pct, 4)

        result = {
            "ticker": ticker.upper(),
            "source": "finnhub",
            "sentiment_score": sentiment_score,
            "company_news_score": sentiment.get("companyNewsScore", 0),
            "sector_avg_bullish": sentiment.get("sectorAverageBullishPercent", 0),
            "sector_avg_news_score": sentiment.get("sectorAverageNewsScore", 0),
            "bullish_percent": bullish_pct,
            "bearish_percent": bearish_pct,
            "buzz": {
                "articles_in_last_week": buzz.get("articlesInLastWeek", 0),
                "buzz_score": buzz.get("buzz", 0),
                "weekly_average": buzz.get("weeklyAverage", 0),
            },
        }
        _set_cache(cache_key, result)
        return result
    except HTTPException:
        raise
    except finnhub.FinnhubAPIException as e:
        status = 503 if "403" in str(e) else 502
        detail = "Finnhub news_sentiment requires a premium plan" if "403" in str(e) else str(e)
        logger.warning(f"Finnhub API error for {ticker}: {e}")
        raise HTTPException(status_code=status, detail=detail)
    except Exception as e:
        logger.error(f"Finnhub sentiment error for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
