import asyncio
import os
import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/sentiment", tags=["Combined Sentiment"])

# Shared httpx client (connection pooling)
_client = httpx.AsyncClient(timeout=30.0)

# Source weights (fixed)
SOURCE_WEIGHTS = {
    "finnhub": 4.0,
    "alphavantage": 3.0,
    "reddit": 3.0,       # scaled by volume_factor
    "stocktwits": 2.5,   # scaled by volume_factor
    "rss": 3.0,          # RSS article-based sentiment (EU + US)
}

FEAR_GREED_BLEND = 0.20  # 20% macro blend


@router.get("/combined/{ticker}")
async def get_combined_sentiment(ticker: str):
    """Aggregate sentiment from 5 sources (Finnhub, Alpha Vantage, Reddit, StockTwits, Fear&Greed) into a unified score."""
    base_url = os.environ.get("MCP_SENTIMENT_INTERNAL_URL", "http://mcp_sentiment:5004")

    async def _fetch(source: str, url: str) -> tuple[str, dict]:
        try:
            resp = await _client.get(url)
            if resp.status_code == 200:
                return source, resp.json()
            return source, {"error": f"HTTP {resp.status_code}", "detail": resp.text}
        except Exception as e:
            return source, {"error": str(e)}

    # Fetch all 6 sources in parallel
    fetches = await asyncio.gather(
        _fetch("reddit", f"{base_url}/sentiment/reddit/{ticker}"),
        _fetch("stocktwits", f"{base_url}/sentiment/stocktwits/{ticker}"),
        _fetch("finnhub", f"{base_url}/sentiment/finnhub/{ticker}"),
        _fetch("alphavantage", f"{base_url}/sentiment/alphavantage/{ticker}"),
        _fetch("fear_greed", f"{base_url}/sentiment/feargreed"),
        _fetch("rss", f"{base_url}/sentiment/rss/{ticker}"),
    )
    results = dict(fetches)

    # --- Ticker-specific sources ---
    ticker_scores = []
    ticker_weights = []
    sources_used = []

    # Finnhub News Sentiment (fixed weight 4.0)
    finnhub = results.get("finnhub", {})
    if "sentiment_score" in finnhub and "error" not in finnhub:
        ticker_scores.append(finnhub["sentiment_score"])
        ticker_weights.append(SOURCE_WEIGHTS["finnhub"])
        sources_used.append("finnhub")

    # Alpha Vantage (fixed weight 3.0)
    alphavantage = results.get("alphavantage", {})
    if "sentiment_score" in alphavantage and "error" not in alphavantage:
        ticker_scores.append(alphavantage["sentiment_score"])
        ticker_weights.append(SOURCE_WEIGHTS["alphavantage"])
        sources_used.append("alphavantage")

    # Reddit (weight 3.0 × volume_factor)
    reddit = results.get("reddit", {})
    if "avg_sentiment" in reddit and reddit.get("mention_count", 0) > 0:
        volume_factor = min(reddit["mention_count"], 50) / 50
        ticker_scores.append(reddit["avg_sentiment"])
        ticker_weights.append(SOURCE_WEIGHTS["reddit"] * volume_factor)
        sources_used.append("reddit")

    # StockTwits (weight 2.5 × volume_factor)
    stocktwits = results.get("stocktwits", {})
    if stocktwits.get("bullish_ratio") is not None and "error" not in stocktwits:
        st_score = (stocktwits["bullish_ratio"] - 0.5) * 2
        volume_factor = min(stocktwits.get("message_count", 0), 50) / 50
        ticker_scores.append(st_score)
        ticker_weights.append(SOURCE_WEIGHTS["stocktwits"] * volume_factor)
        sources_used.append("stocktwits")

    # RSS article-based sentiment (weight 3.0 × volume_factor)
    rss = results.get("rss", {})
    if rss.get("sentiment_score") is not None and "error" not in rss:
        rss_volume = min(rss.get("article_count", 0), 20) / 20
        ticker_scores.append(rss["sentiment_score"])
        ticker_weights.append(SOURCE_WEIGHTS["rss"] * rss_volume)
        sources_used.append("rss")

    # --- Macro source: Fear & Greed ---
    fear_greed = results.get("fear_greed", {})
    fg_score = None
    macro_sentiment = None
    if "sentiment_score" in fear_greed and "error" not in fear_greed:
        fg_score = fear_greed["sentiment_score"]
        sources_used.append("fear_greed")
        macro_sentiment = {
            "fear_greed_score": fg_score,
            "fear_greed_raw": fear_greed.get("raw_score"),
            "fear_greed_label": fear_greed.get("label"),
        }

    # --- Compute unified score ---
    if ticker_scores and sum(ticker_weights) > 0:
        ticker_unified = sum(s * w for s, w in zip(ticker_scores, ticker_weights)) / sum(ticker_weights)

        if fg_score is not None:
            unified_score = round((1 - FEAR_GREED_BLEND) * ticker_unified + FEAR_GREED_BLEND * fg_score, 3)
        else:
            unified_score = round(ticker_unified, 3)

        if unified_score > 0.1:
            unified_label = "bullish"
        elif unified_score < -0.1:
            unified_label = "bearish"
        else:
            unified_label = "neutral"
    else:
        unified_score = None
        unified_label = "insufficient_data"

    response = {
        "ticker": ticker.upper(),
        "unified_score": unified_score,
        "unified_label": unified_label,
        "source_count": len(sources_used),
        "sources_used": sources_used,
        "sources": results,
    }
    if macro_sentiment:
        response["macro_sentiment"] = macro_sentiment

    return response
