import asyncio
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter

from mcp_market_data.tools._ticker_pool import get_ticker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/market", tags=["Market Overview"])

INDICES = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq 100",
    "DIA": "Dow Jones",
    "IWM": "Russell 2000",
    "^VIX": "VIX (Volatility)",
}

SECTOR_ETFS = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLV": "Healthcare",
    "XLE": "Energy",
    "XLI": "Industrials",
    "XLP": "Consumer Staples",
    "XLY": "Consumer Discretionary",
    "XLU": "Utilities",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
}

# In-memory cache with TTL
_cache = {
    "data": None,
    "expires_at": None,
}
CACHE_TTL_SECONDS = 60


async def _fetch_ticker_info(symbol: str, name: str, is_index: bool = False) -> dict:
    """Fetch ticker info in a thread pool to avoid blocking."""
    try:
        info = await asyncio.wait_for(
            asyncio.to_thread(lambda: get_ticker(symbol).info),
            timeout=10.0
        )
        result = {
            "symbol": symbol,
            "name": name,
            "price": info.get("regularMarketPrice"),
            "change_percent": info.get("regularMarketChangePercent"),
        }
        if is_index:
            result["change"] = info.get("regularMarketChange")
        return result
    except asyncio.TimeoutError:
        logger.warning(f"Timeout fetching {symbol}")
        return {"symbol": symbol, "name": name, "error": "Timeout"}
    except Exception as e:
        logger.warning(f"Error fetching {symbol}: {e}")
        return {"symbol": symbol, "name": name, "error": "Failed to fetch"}


@router.get("/overview")
async def get_market_overview():
    """Get market overview: major indices and sector ETF performance.

    Results are cached for 60 seconds to improve performance.
    All tickers are fetched in parallel.
    """
    now = datetime.now()

    # Return cached data if valid
    if _cache["data"] is not None and _cache["expires_at"] and now < _cache["expires_at"]:
        logger.debug("Returning cached market overview")
        return _cache["data"]

    # Fetch all tickers in parallel
    index_tasks = [
        _fetch_ticker_info(symbol, name, is_index=True)
        for symbol, name in INDICES.items()
    ]
    sector_tasks = [
        _fetch_ticker_info(symbol, name, is_index=False)
        for symbol, name in SECTOR_ETFS.items()
    ]

    all_results = await asyncio.gather(*index_tasks, *sector_tasks)

    indices = all_results[:len(INDICES)]
    sectors = all_results[len(INDICES):]

    result = {
        "indices": indices,
        "sectors": sectors,
        "cached_at": now.isoformat(),
    }

    # Update cache
    _cache["data"] = result
    _cache["expires_at"] = now + timedelta(seconds=CACHE_TTL_SECONDS)

    return result
