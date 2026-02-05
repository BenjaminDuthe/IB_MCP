import os
import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/sentiment", tags=["Combined Sentiment"])


@router.get("/combined/{ticker}")
async def get_combined_sentiment(ticker: str):
    """Aggregate sentiment from Reddit and StockTwits into a unified score."""
    base_url = os.environ.get("MCP_SENTIMENT_INTERNAL_URL", "http://mcp_sentiment:5004")
    results = {}

    async with httpx.AsyncClient(timeout=30) as client:
        # Fetch Reddit sentiment
        try:
            resp = await client.get(f"{base_url}/sentiment/reddit/{ticker}")
            if resp.status_code == 200:
                results["reddit"] = resp.json()
            else:
                results["reddit"] = {"error": f"HTTP {resp.status_code}", "detail": resp.text}
        except Exception as e:
            results["reddit"] = {"error": str(e)}

        # Fetch StockTwits sentiment
        try:
            resp = await client.get(f"{base_url}/sentiment/stocktwits/{ticker}")
            if resp.status_code == 200:
                results["stocktwits"] = resp.json()
            else:
                results["stocktwits"] = {"error": f"HTTP {resp.status_code}", "detail": resp.text}
        except Exception as e:
            results["stocktwits"] = {"error": str(e)}

    # Calculate unified score
    scores = []
    weights = []

    reddit = results.get("reddit", {})
    if "avg_sentiment" in reddit and reddit.get("mention_count", 0) > 0:
        scores.append(reddit["avg_sentiment"])
        weights.append(min(reddit["mention_count"], 50))

    stocktwits = results.get("stocktwits", {})
    if stocktwits.get("bullish_ratio") is not None:
        # Convert bullish_ratio (0-1) to polarity scale (-1 to 1)
        st_score = (stocktwits["bullish_ratio"] - 0.5) * 2
        scores.append(st_score)
        weights.append(min(stocktwits.get("message_count", 0), 50))

    if scores and sum(weights) > 0:
        unified_score = round(sum(s * w for s, w in zip(scores, weights)) / sum(weights), 3)
        if unified_score > 0.1:
            unified_label = "bullish"
        elif unified_score < -0.1:
            unified_label = "bearish"
        else:
            unified_label = "neutral"
    else:
        unified_score = None
        unified_label = "insufficient_data"

    return {
        "ticker": ticker.upper(),
        "unified_score": unified_score,
        "unified_label": unified_label,
        "sources": results,
    }
