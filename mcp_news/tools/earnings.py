import asyncio
import os
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/news", tags=["Earnings Calendar"])

# In-memory cache for earnings (TTL: 5 minutes)
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
        import finnhub
        api_key = os.environ.get("FINNHUB_API_KEY")
        if not api_key:
            return None
        _finnhub_client = finnhub.Client(api_key=api_key)
    return _finnhub_client


@router.get("/earnings")
async def get_earnings_calendar(
    days: int = Query(7, ge=1, le=30, description="Number of days ahead to look"),
):
    """Get upcoming earnings calendar from Finnhub.

    Results are cached for 5 minutes to reduce API calls.
    """
    cache_key = f"earnings:{days}"
    cached = _get_cached(cache_key)
    if cached:
        return cached

    client = _get_finnhub_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Finnhub API not configured. Set FINNHUB_API_KEY.")

    try:
        today = datetime.now()
        from_date = today.strftime("%Y-%m-%d")
        to_date = (today + timedelta(days=days)).strftime("%Y-%m-%d")

        calendar = await asyncio.to_thread(
            lambda: client.earnings_calendar(_from=from_date, to=to_date, symbol="", international=False)
        )

        earnings = []
        for item in calendar.get("earningsCalendar", [])[:50]:
            earnings.append({
                "symbol": item.get("symbol"),
                "date": item.get("date"),
                "hour": item.get("hour"),
                "eps_estimate": item.get("epsEstimate"),
                "eps_actual": item.get("epsActual"),
                "revenue_estimate": item.get("revenueEstimate"),
                "revenue_actual": item.get("revenueActual"),
                "quarter": item.get("quarter"),
                "year": item.get("year"),
            })

        result = {
            "period": f"{from_date} to {to_date}",
            "earnings_count": len(earnings),
            "earnings": earnings,
        }
        _set_cache(cache_key, result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
