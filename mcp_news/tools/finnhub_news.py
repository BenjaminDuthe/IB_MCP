import asyncio
import os
import logging
import finnhub
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/news", tags=["Finnhub News"])

# In-memory cache for news endpoints (TTL: 5 minutes)
_cache = {}
CACHE_TTL_SECONDS = 300


def _get_cached(key: str) -> dict | None:
    """Get cached data if not expired."""
    if key in _cache:
        entry = _cache[key]
        if datetime.now() < entry["expires_at"]:
            logger.debug(f"Cache hit for {key}")
            return entry["data"]
        del _cache[key]
    return None


def _set_cache(key: str, data: dict) -> None:
    """Set cache with TTL."""
    _cache[key] = {
        "data": data,
        "expires_at": datetime.now() + timedelta(seconds=CACHE_TTL_SECONDS),
    }


_finnhub_client = None


def _get_finnhub_client():
    """Get or create a singleton Finnhub client."""
    global _finnhub_client
    if _finnhub_client is None:
        api_key = os.environ.get("FINNHUB_API_KEY")
        if not api_key:
            return None
        _finnhub_client = finnhub.Client(api_key=api_key)
    return _finnhub_client


@router.get("/stock/{ticker}")
async def get_stock_news(
    ticker: str,
    days: int = Query(7, ge=1, le=30, description="Number of days to look back"),
):
    """Get recent news articles for a specific stock ticker from Finnhub.

    Results are cached for 5 minutes to reduce API calls.
    """
    cache_key = f"stock_news:{ticker.upper()}:{days}"
    cached = _get_cached(cache_key)
    if cached:
        return cached

    client = _get_finnhub_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Finnhub API not configured. Set FINNHUB_API_KEY.")

    try:
        today = datetime.now()
        from_date = (today - timedelta(days=days)).strftime("%Y-%m-%d")
        to_date = today.strftime("%Y-%m-%d")

        news = await asyncio.to_thread(client.company_news, ticker.upper(), from_date, to_date)

        articles = []
        for item in news[:20]:
            articles.append({
                "headline": item.get("headline"),
                "summary": item.get("summary", "")[:300],
                "source": item.get("source"),
                "url": item.get("url"),
                "datetime": datetime.fromtimestamp(item.get("datetime", 0)).isoformat(),
                "category": item.get("category"),
                "related": item.get("related"),
            })

        result = {
            "ticker": ticker.upper(),
            "period": f"{from_date} to {to_date}",
            "article_count": len(articles),
            "articles": articles,
        }
        _set_cache(cache_key, result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/market")
async def get_market_news(
    category: str = Query("general", description="Category: general, forex, crypto, merger"),
):
    """Get general market news from Finnhub by category.

    Results are cached for 5 minutes to reduce API calls.
    """
    cache_key = f"market_news:{category}"
    cached = _get_cached(cache_key)
    if cached:
        return cached

    client = _get_finnhub_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Finnhub API not configured. Set FINNHUB_API_KEY.")

    try:
        news = await asyncio.to_thread(client.general_news, category, 0)

        articles = []
        for item in news[:20]:
            articles.append({
                "headline": item.get("headline"),
                "summary": item.get("summary", "")[:300],
                "source": item.get("source"),
                "url": item.get("url"),
                "datetime": datetime.fromtimestamp(item.get("datetime", 0)).isoformat(),
                "category": item.get("category"),
            })

        result = {
            "category": category,
            "article_count": len(articles),
            "articles": articles,
        }
        _set_cache(cache_key, result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
