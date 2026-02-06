import asyncio
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException

from mcp_market_data.tools._ticker_pool import get_ticker

router = APIRouter(prefix="/stock", tags=["Fundamentals"])

# In-memory cache for fundamentals (TTL: 60 seconds)
_fundamentals_cache = {}
FUNDAMENTALS_CACHE_TTL = 60


def _get_cached(key: str) -> dict | None:
    if key in _fundamentals_cache:
        entry = _fundamentals_cache[key]
        if datetime.now() < entry["expires_at"]:
            return entry["data"]
        del _fundamentals_cache[key]
    return None


def _set_cache(key: str, data: dict) -> None:
    _fundamentals_cache[key] = {"data": data, "expires_at": datetime.now() + timedelta(seconds=FUNDAMENTALS_CACHE_TTL)}


def _fetch_ticker_info(ticker: str) -> dict:
    """Fetch ticker info synchronously (for use with to_thread)."""
    return get_ticker(ticker).info


@router.get("/fundamentals/{ticker}")
async def get_fundamentals(ticker: str):
    """Get fundamental data: P/E, market cap, revenue, EPS, dividend yield, sector."""
    cache_key = f"fundamentals:{ticker.upper()}"
    cached = _get_cached(cache_key)
    if cached:
        return cached

    try:
        info = await asyncio.to_thread(_fetch_ticker_info, ticker.upper())
        if not info or "shortName" not in info:
            raise HTTPException(status_code=404, detail=f"No data found for {ticker}")
        result = {
            "ticker": ticker.upper(),
            "name": info.get("shortName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "market_cap": info.get("marketCap"),
            "enterprise_value": info.get("enterpriseValue"),
            "trailing_pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "peg_ratio": info.get("pegRatio"),
            "price_to_book": info.get("priceToBook"),
            "revenue": info.get("totalRevenue"),
            "revenue_growth": info.get("revenueGrowth"),
            "earnings_growth": info.get("earningsGrowth"),
            "eps_trailing": info.get("trailingEps"),
            "eps_forward": info.get("forwardEps"),
            "dividend_yield": info.get("dividendYield"),
            "dividend_rate": info.get("dividendRate"),
            "profit_margin": info.get("profitMargins"),
            "operating_margin": info.get("operatingMargins"),
            "return_on_equity": info.get("returnOnEquity"),
            "debt_to_equity": info.get("debtToEquity"),
            "free_cash_flow": info.get("freeCashflow"),
            "beta": info.get("beta"),
            "52_week_high": info.get("fiftyTwoWeekHigh"),
            "52_week_low": info.get("fiftyTwoWeekLow"),
        }
        _set_cache(cache_key, result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analyst/{ticker}")
async def get_analyst_recommendations(ticker: str):
    """Get analyst consensus: buy/hold/sell counts and price targets."""
    try:
        info = await asyncio.to_thread(_fetch_ticker_info, ticker.upper())
        recommendations = None
        try:
            t = get_ticker(ticker.upper())
            recs = await asyncio.to_thread(lambda: t.recommendations)
            if recs is not None and not recs.empty:
                recent = recs.tail(10)
                recommendations = recent.reset_index().to_dict(orient="records")
        except Exception:
            pass

        return {
            "ticker": ticker.upper(),
            "recommendation_key": info.get("recommendationKey"),
            "recommendation_mean": info.get("recommendationMean"),
            "number_of_analysts": info.get("numberOfAnalystOpinions"),
            "target_high": info.get("targetHighPrice"),
            "target_low": info.get("targetLowPrice"),
            "target_mean": info.get("targetMeanPrice"),
            "target_median": info.get("targetMedianPrice"),
            "current_price": info.get("currentPrice"),
            "recent_recommendations": recommendations,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/insiders/{ticker}")
async def get_insider_trades(ticker: str):
    """Get recent insider transactions for a ticker."""
    try:
        insider_transactions = None
        try:
            t = get_ticker(ticker.upper())
            txns = await asyncio.to_thread(lambda: t.insider_transactions)
            if txns is not None and not txns.empty:
                recent = txns.head(20)
                insider_transactions = recent.to_dict(orient="records")
        except Exception:
            pass

        insider_holders = None
        try:
            holders = await asyncio.to_thread(lambda: t.insider_holders)
            if holders is not None and not holders.empty:
                insider_holders = holders.to_dict(orient="records")
        except Exception:
            pass

        return {
            "ticker": ticker.upper(),
            "insider_transactions": insider_transactions,
            "insider_holders": insider_holders,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
