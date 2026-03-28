"""yfinance News Sentiment — ticker-specific news from Yahoo Finance."""

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sentiment", tags=["yfinance News"])

# Cache: ticker → (result, timestamp)
_cache: dict[str, tuple[dict, float]] = {}
CACHE_TTL = 600  # 10 min — news change frequently, short TTL to stay current

# Reuse keyword sets from rss_sentiment
BULLISH = {"surge", "rally", "growth", "profit", "beat", "upgrade", "buy", "bullish",
           "record", "strong", "outperform", "dividend", "acquisition", "raise", "exceed",
           "hausse", "rebond", "croissance", "benefice", "achat", "optimisme"}
BEARISH = {"drop", "fall", "loss", "miss", "downgrade", "sell", "bearish", "crash",
           "decline", "weak", "underperform", "layoff", "debt", "warning", "cut", "recall",
           "baisse", "chute", "perte", "risque", "licenciement", "alerte"}


def _score_text(text: str) -> float:
    """Keyword sentiment score for a news title/summary."""
    text = text.lower()
    bull = sum(1 for w in BULLISH if w in text)
    bear = sum(1 for w in BEARISH if w in text)
    total = bull + bear
    if total == 0:
        return 0.0
    return (bull - bear) / total


@router.get("/yfinance/{ticker}")
async def get_yfinance_news_sentiment(ticker: str):
    """Get sentiment from Yahoo Finance news for a specific ticker."""
    ticker = ticker.upper()
    now = datetime.utcnow().timestamp()

    # Check cache
    if ticker in _cache:
        cached, ts = _cache[ticker]
        if now - ts < CACHE_TTL:
            return cached

    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        news = await asyncio.to_thread(lambda: t.news)
    except Exception as e:
        logger.error("yfinance news failed for %s: %s", ticker, e)
        return {
            "ticker": ticker,
            "sentiment_score": None,
            "article_count": 0,
            "error": str(e),
        }

    if not news:
        result = {
            "ticker": ticker,
            "sentiment_score": None,
            "article_count": 0,
            "label": "no_data",
        }
        _cache[ticker] = (result, now)
        return result

    scores = []
    articles = []
    for item in news[:15]:
        title = item.get("title", "")
        publisher = item.get("publisher", "")
        score = _score_text(title)
        scores.append(score)
        articles.append({
            "title": title,
            "publisher": publisher,
            "sentiment": round(score, 2),
        })

    avg_score = sum(scores) / len(scores) if scores else 0.0
    label = "bullish" if avg_score > 0.1 else ("bearish" if avg_score < -0.1 else "neutral")

    result = {
        "ticker": ticker,
        "sentiment_score": round(avg_score, 3),
        "article_count": len(articles),
        "label": label,
        "top_articles": articles[:5],
    }
    _cache[ticker] = (result, now)
    return result
