import asyncio
from fastapi import APIRouter, HTTPException, Query

from mcp_market_data.tools._ticker_pool import get_ticker

router = APIRouter(prefix="/stock", tags=["History"])


def _fetch_history(ticker: str, period: str, interval: str):
    """Fetch ticker history synchronously (for use with to_thread)."""
    return get_ticker(ticker).history(period=period, interval=interval)


@router.get("/history/{ticker}")
async def get_history(
    ticker: str,
    period: str = Query("1mo", description="Period: 1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,ytd,max"),
    interval: str = Query("1d", description="Interval: 1m,2m,5m,15m,30m,60m,90m,1h,1d,5d,1wk,1mo,3mo"),
):
    """Get OHLCV historical data for a ticker with configurable period and interval."""
    try:
        hist = await asyncio.to_thread(_fetch_history, ticker.upper(), period, interval)

        if hist.empty:
            raise HTTPException(status_code=404, detail=f"No history for {ticker}")

        records = []
        for date, row in hist.iterrows():
            records.append({
                "date": str(date),
                "open": round(row["Open"], 2),
                "high": round(row["High"], 2),
                "low": round(row["Low"], 2),
                "close": round(row["Close"], 2),
                "volume": int(row["Volume"]),
            })

        return {
            "ticker": ticker.upper(),
            "period": period,
            "interval": interval,
            "data_points": len(records),
            "history": records,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
