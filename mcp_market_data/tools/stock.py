import asyncio
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Query

from mcp_market_data.tools._ticker_pool import get_ticker

router = APIRouter(prefix="/stock", tags=["Stock"])

# In-memory cache for stock prices (TTL: 60 seconds)
_price_cache = {}
PRICE_CACHE_TTL = 60


def _get_cached(cache: dict, key: str) -> dict | None:
    if key in cache:
        entry = cache[key]
        if datetime.now() < entry["expires_at"]:
            return entry["data"]
        del cache[key]
    return None


def _set_cache(cache: dict, key: str, data: dict, ttl: int) -> None:
    cache[key] = {"data": data, "expires_at": datetime.now() + timedelta(seconds=ttl)}


def _fetch_ticker_info(ticker: str) -> dict:
    """Fetch ticker info synchronously (for use with to_thread)."""
    return get_ticker(ticker).info


@router.get("/price/{ticker}")
async def get_stock_price(ticker: str):
    """Get current stock price, change, volume, and day range for a ticker."""
    cache_key = f"price:{ticker.upper()}"
    cached = _get_cached(_price_cache, cache_key)
    if cached:
        return cached

    try:
        info = await asyncio.to_thread(_fetch_ticker_info, ticker.upper())
        if not info or "regularMarketPrice" not in info:
            raise HTTPException(status_code=404, detail=f"No data found for {ticker}")
        result = {
            "ticker": ticker.upper(),
            "price": info.get("regularMarketPrice"),
            "previous_close": info.get("regularMarketPreviousClose"),
            "change": info.get("regularMarketChange"),
            "change_percent": info.get("regularMarketChangePercent"),
            "volume": info.get("regularMarketVolume"),
            "day_high": info.get("regularMarketDayHigh"),
            "day_low": info.get("regularMarketDayLow"),
            "market_cap": info.get("marketCap"),
            "currency": info.get("currency"),
        }
        _set_cache(_price_cache, cache_key, result, PRICE_CACHE_TTL)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/compare")
async def compare_stocks(tickers: str = Query(..., description="Comma-separated tickers, e.g. AAPL,MSFT,GOOGL")):
    """Compare multiple stocks side by side: price, change, volume, market cap."""
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if len(ticker_list) < 2:
        raise HTTPException(status_code=400, detail="Provide at least 2 tickers")
    if len(ticker_list) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 tickers")

    async def _fetch_one(symbol: str) -> dict:
        try:
            info = await asyncio.to_thread(_fetch_ticker_info, symbol)
            return {
                "ticker": symbol,
                "price": info.get("regularMarketPrice"),
                "change_percent": info.get("regularMarketChangePercent"),
                "volume": info.get("regularMarketVolume"),
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "dividend_yield": info.get("dividendYield"),
            }
        except Exception:
            return {"ticker": symbol, "error": "Failed to fetch data"}

    results = await asyncio.gather(*[_fetch_one(s) for s in ticker_list])
    return {"comparison": list(results)}
