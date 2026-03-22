import asyncio
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Query

from mcp_market_data.tools._ticker_pool import get_ticker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stock", tags=["Deep Analysis"])

_cache = {}
CACHE_TTL = 300  # 5 min


def _get_cached(key: str) -> dict | None:
    if key in _cache:
        entry = _cache[key]
        if datetime.now() < entry["expires_at"]:
            return entry["data"]
        del _cache[key]
    return None


def _set_cache(key: str, data: dict) -> None:
    _cache[key] = {"data": data, "expires_at": datetime.now() + timedelta(seconds=CACHE_TTL)}


def _safe_df_to_records(df, limit: int = 10) -> list | None:
    """Safely convert a DataFrame to list of dicts."""
    if df is None or (hasattr(df, 'empty') and df.empty):
        return None
    try:
        records = df.head(limit).reset_index().to_dict(orient="records")
        # Convert Timestamps to strings
        for rec in records:
            for k, v in rec.items():
                if hasattr(v, 'isoformat'):
                    rec[k] = v.isoformat()
                elif hasattr(v, 'item'):
                    rec[k] = v.item()
        return records
    except Exception:
        return None


@router.get("/earnings/{ticker}")
async def get_earnings(ticker: str):
    """Get earnings history, upcoming dates, and earnings surprises."""
    cache_key = f"earnings:{ticker.upper()}"
    cached = _get_cached(cache_key)
    if cached:
        return cached

    try:
        t = get_ticker(ticker.upper())

        earnings_history = await asyncio.to_thread(lambda: _safe_df_to_records(t.earnings_history, 12))
        earnings_dates = await asyncio.to_thread(lambda: _safe_df_to_records(t.earnings_dates, 4))
        quarterly_earnings = await asyncio.to_thread(lambda: _safe_df_to_records(t.quarterly_earnings, 8))

        info = await asyncio.to_thread(lambda: t.info)

        result = {
            "ticker": ticker.upper(),
            "eps_trailing": info.get("trailingEps"),
            "eps_forward": info.get("forwardEps"),
            "earnings_growth": info.get("earningsGrowth"),
            "revenue_growth": info.get("revenueGrowth"),
            "earnings_quarterly_growth": info.get("earningsQuarterlyGrowth"),
            "next_earnings_date": earnings_dates[0] if earnings_dates else None,
            "earnings_history": earnings_history,
            "quarterly_earnings": quarterly_earnings,
        }
        _set_cache(cache_key, result)
        return result
    except Exception as e:
        logger.error(f"Earnings error for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/financials/{ticker}")
async def get_financials(ticker: str):
    """Get income statement, balance sheet, and cash flow (quarterly)."""
    cache_key = f"financials:{ticker.upper()}"
    cached = _get_cached(cache_key)
    if cached:
        return cached

    try:
        t = get_ticker(ticker.upper())

        income = await asyncio.to_thread(lambda: _safe_df_to_records(t.quarterly_income_stmt.T, 4))
        balance = await asyncio.to_thread(lambda: _safe_df_to_records(t.quarterly_balance_sheet.T, 4))
        cashflow = await asyncio.to_thread(lambda: _safe_df_to_records(t.quarterly_cashflow.T, 4))

        result = {
            "ticker": ticker.upper(),
            "income_statement": income,
            "balance_sheet": balance,
            "cash_flow": cashflow,
        }
        _set_cache(cache_key, result)
        return result
    except Exception as e:
        logger.error(f"Financials error for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/holders/{ticker}")
async def get_holders(ticker: str):
    """Get institutional holders, mutual fund holders, and ownership breakdown."""
    cache_key = f"holders:{ticker.upper()}"
    cached = _get_cached(cache_key)
    if cached:
        return cached

    try:
        t = get_ticker(ticker.upper())

        institutional = await asyncio.to_thread(lambda: _safe_df_to_records(t.institutional_holders, 15))
        mutual_funds = await asyncio.to_thread(lambda: _safe_df_to_records(t.mutualfund_holders, 15))

        info = await asyncio.to_thread(lambda: t.info)

        result = {
            "ticker": ticker.upper(),
            "held_by_insiders": info.get("heldPercentInsiders"),
            "held_by_institutions": info.get("heldPercentInstitutions"),
            "float_shares": info.get("floatShares"),
            "shares_outstanding": info.get("sharesOutstanding"),
            "shares_short": info.get("sharesShort"),
            "short_ratio": info.get("shortRatio"),
            "short_percent_of_float": info.get("shortPercentOfFloat"),
            "institutional_holders": institutional,
            "mutual_fund_holders": mutual_funds,
        }
        _set_cache(cache_key, result)
        return result
    except Exception as e:
        logger.error(f"Holders error for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sector-performance")
async def get_sector_performance():
    """Get performance of major sector ETFs (XLK, XLF, XLE, XLV, XLI, XLP, XLU, XLY, XLC, XLRE, XLB)."""
    cache_key = "sector_perf"
    cached = _get_cached(cache_key)
    if cached:
        return cached

    sectors = {
        "XLK": "Technology", "XLF": "Financials", "XLE": "Energy",
        "XLV": "Healthcare", "XLI": "Industrials", "XLP": "Consumer Staples",
        "XLU": "Utilities", "XLY": "Consumer Discretionary",
        "XLC": "Communication", "XLRE": "Real Estate", "XLB": "Materials",
    }

    async def _fetch_sector(etf: str, name: str) -> dict:
        try:
            info = await asyncio.to_thread(lambda: get_ticker(etf).info)
            return {
                "etf": etf,
                "sector": name,
                "price": info.get("regularMarketPrice"),
                "change_percent": info.get("regularMarketChangePercent"),
                "volume": info.get("regularMarketVolume"),
            }
        except Exception:
            return {"etf": etf, "sector": name, "error": "Failed"}

    results = await asyncio.gather(*[_fetch_sector(etf, name) for etf, name in sectors.items()])
    sorted_results = sorted(
        [r for r in results if "error" not in r],
        key=lambda x: x.get("change_percent", 0),
        reverse=True,
    )

    result = {"sectors": sorted_results, "timestamp": datetime.now().isoformat()}
    _set_cache(cache_key, result)
    return result


@router.get("/market-overview")
async def get_market_overview():
    """Get broad market overview: major indices, VIX, treasuries, commodities."""
    cache_key = "market_overview"
    cached = _get_cached(cache_key)
    if cached:
        return cached

    symbols = {
        "^GSPC": "S&P 500", "^DJI": "Dow Jones", "^IXIC": "Nasdaq",
        "^RUT": "Russell 2000", "^VIX": "VIX",
        "^TNX": "10Y Treasury", "^FVX": "5Y Treasury",
        "GC=F": "Gold", "CL=F": "Crude Oil", "BTC-USD": "Bitcoin",
        "DX-Y.NYB": "US Dollar Index",
    }

    async def _fetch_symbol(sym: str, name: str) -> dict:
        try:
            info = await asyncio.to_thread(lambda: get_ticker(sym).info)
            return {
                "symbol": sym,
                "name": name,
                "price": info.get("regularMarketPrice"),
                "change_percent": info.get("regularMarketChangePercent"),
            }
        except Exception:
            return {"symbol": sym, "name": name, "error": "Failed"}

    results = await asyncio.gather(*[_fetch_symbol(s, n) for s, n in symbols.items()])

    result = {"markets": list(results), "timestamp": datetime.now().isoformat()}
    _set_cache(cache_key, result)
    return result
