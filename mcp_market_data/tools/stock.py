from fastapi import APIRouter, HTTPException, Query
import yfinance as yf

router = APIRouter(prefix="/stock", tags=["Stock"])


@router.get("/price/{ticker}")
async def get_stock_price(ticker: str):
    """Get current stock price, change, volume, and day range for a ticker."""
    try:
        t = yf.Ticker(ticker.upper())
        info = t.info
        if not info or "regularMarketPrice" not in info:
            raise HTTPException(status_code=404, detail=f"No data found for {ticker}")
        return {
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

    results = []
    for symbol in ticker_list:
        try:
            t = yf.Ticker(symbol)
            info = t.info
            results.append({
                "ticker": symbol,
                "price": info.get("regularMarketPrice"),
                "change_percent": info.get("regularMarketChangePercent"),
                "volume": info.get("regularMarketVolume"),
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "dividend_yield": info.get("dividendYield"),
            })
        except Exception:
            results.append({"ticker": symbol, "error": "Failed to fetch data"})

    return {"comparison": results}
