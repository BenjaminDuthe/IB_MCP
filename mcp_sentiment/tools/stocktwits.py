import time
import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/sentiment", tags=["StockTwits Sentiment"])

STOCKTWITS_BASE = "https://api.stocktwits.com/api/2"
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; IB_MCP/1.0)",
    "Accept": "application/json",
}

# Shared httpx client (connection pooling)
_client = httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=15.0)

# Circuit breaker: avoid hammering a blocked API
_circuit = {"open": False, "last_check": 0.0, "cooldown": 300}  # 5 min cooldown


@router.get("/stocktwits/{ticker}")
async def get_stocktwits_sentiment(ticker: str):
    """Get StockTwits sentiment for a ticker: bullish/bearish ratio, message volume."""
    # Circuit breaker: if API was recently blocked, fail fast
    if _circuit["open"] and (time.time() - _circuit["last_check"]) < _circuit["cooldown"]:
        raise HTTPException(
            status_code=503,
            detail=f"StockTwits API unavailable (Cloudflare protection). Retry in {int(_circuit['cooldown'] - (time.time() - _circuit['last_check']))}s"
        )

    try:
        resp = await _client.get(f"{STOCKTWITS_BASE}/streams/symbol/{ticker.upper()}.json")

        if resp.status_code == 403:
            _circuit["open"] = True
            _circuit["last_check"] = time.time()
            raise HTTPException(status_code=503, detail="StockTwits API blocked by Cloudflare protection")
        if resp.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Ticker {ticker} not found on StockTwits")
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="StockTwits API error")

        # API accessible: reset circuit breaker
        _circuit["open"] = False

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
    if _circuit["open"] and (time.time() - _circuit["last_check"]) < _circuit["cooldown"]:
        raise HTTPException(status_code=503, detail="StockTwits API unavailable (Cloudflare protection)")

    try:
        resp = await _client.get(f"{STOCKTWITS_BASE}/trending/symbols.json")

        if resp.status_code == 403:
            _circuit["open"] = True
            _circuit["last_check"] = time.time()
            raise HTTPException(status_code=503, detail="StockTwits API blocked by Cloudflare protection")
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="StockTwits API error")

        _circuit["open"] = False

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
