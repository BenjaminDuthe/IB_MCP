import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/sentiment", tags=["StockTwits Sentiment"])

STOCKTWITS_BASE = "https://api.stocktwits.com/api/2"


@router.get("/stocktwits/{ticker}")
async def get_stocktwits_sentiment(ticker: str):
    """Get StockTwits sentiment for a ticker: bullish/bearish ratio, message volume."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{STOCKTWITS_BASE}/streams/symbol/{ticker.upper()}.json")

        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Ticker {ticker} not found on StockTwits")
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="StockTwits API error")

        data = resp.json()
        messages = data.get("messages", [])

        bullish = 0
        bearish = 0
        total = len(messages)

        recent_messages = []
        for msg in messages:
            sentiment = msg.get("entities", {}).get("sentiment")
            if sentiment:
                if sentiment.get("basic") == "Bullish":
                    bullish += 1
                elif sentiment.get("basic") == "Bearish":
                    bearish += 1

            recent_messages.append({
                "body": msg.get("body", "")[:200],
                "sentiment": sentiment.get("basic") if sentiment else None,
                "created_at": msg.get("created_at"),
                "likes": msg.get("likes", {}).get("total", 0),
            })

        sentiment_total = bullish + bearish
        bullish_ratio = round(bullish / sentiment_total, 2) if sentiment_total > 0 else None

        return {
            "ticker": ticker.upper(),
            "source": "stocktwits",
            "message_count": total,
            "bullish": bullish,
            "bearish": bearish,
            "bullish_ratio": bullish_ratio,
            "recent_messages": recent_messages[:10],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trending")
async def get_trending_tickers():
    """Get trending tickers from StockTwits."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{STOCKTWITS_BASE}/trending/symbols.json")

        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="StockTwits API error")

        data = resp.json()
        symbols = data.get("symbols", [])

        trending = []
        for s in symbols:
            trending.append({
                "symbol": s.get("symbol"),
                "title": s.get("title"),
                "watchlist_count": s.get("watchlist_count"),
            })

        return {"trending": trending}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
