from fastapi import APIRouter, HTTPException
import yfinance as yf

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


@router.get("/overview")
async def get_market_overview():
    """Get market overview: major indices and sector ETF performance."""
    indices = []
    for symbol, name in INDICES.items():
        try:
            t = yf.Ticker(symbol)
            info = t.info
            indices.append({
                "symbol": symbol,
                "name": name,
                "price": info.get("regularMarketPrice"),
                "change": info.get("regularMarketChange"),
                "change_percent": info.get("regularMarketChangePercent"),
            })
        except Exception:
            indices.append({"symbol": symbol, "name": name, "error": "Failed to fetch"})

    sectors = []
    for symbol, name in SECTOR_ETFS.items():
        try:
            t = yf.Ticker(symbol)
            info = t.info
            sectors.append({
                "symbol": symbol,
                "name": name,
                "price": info.get("regularMarketPrice"),
                "change_percent": info.get("regularMarketChangePercent"),
            })
        except Exception:
            sectors.append({"symbol": symbol, "name": name, "error": "Failed to fetch"})

    return {
        "indices": indices,
        "sectors": sectors,
    }
