"""RSS-based sentiment for EU tickers — queries MongoDB raw_articles."""

import logging
import os
import re
from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sentiment", tags=["RSS Sentiment"])

MONGODB_URI = os.environ.get("MONGODB_URI", "")

# Ticker → company name variants for article matching
TICKER_NAMES = {
    "MC.PA": ["lvmh", "louis vuitton", "moet hennessy"],
    "SU.PA": ["schneider electric", "schneider"],
    "AIR.PA": ["airbus"],
    "BNP.PA": ["bnp paribas", "bnp"],
    "SAF.PA": ["safran"],
    "TTE.PA": ["totalenergies", "total energies", "total se"],
    "OR.PA": ["l'oreal", "loreal", "l'oréal"],
    "ASML.AS": ["asml"],
    "SAP.DE": ["sap se", "sap"],
    "SIE.DE": ["siemens"],
    # US tickers also work
    "NVDA": ["nvidia"],
    "MSFT": ["microsoft"],
    "GOOGL": ["google", "alphabet"],
    "AMZN": ["amazon"],
    "META": ["meta platforms", "meta", "facebook"],
    "AAPL": ["apple"],
    "TSLA": ["tesla"],
    "AMD": ["amd", "advanced micro"],
    "NFLX": ["netflix"],
    "JPM": ["jpmorgan", "jp morgan"],
    "LLY": ["eli lilly", "lilly"],
    "BA": ["boeing"],
    "XOM": ["exxonmobil", "exxon"],
}

# French + English sentiment keywords
BULLISH_FR = {"hausse", "progression", "croissance", "rebond", "record", "benefice", "bénéfice",
              "profit", "dividende", "acquisition", "optimisme", "surperformance", "recommandation",
              "achat", "relèvement", "objectif", "résultats solides", "confiance"}
BEARISH_FR = {"baisse", "chute", "recul", "perte", "crise", "alerte", "avertissement",
              "dégradation", "vente", "risque", "inquiétude", "ralentissement", "dette",
              "restructuration", "licenciement", "déficit", "sous-performance"}
BULLISH_EN = {"surge", "rally", "growth", "profit", "beat", "upgrade", "buy", "bullish",
              "record", "strong", "outperform", "dividend", "acquisition"}
BEARISH_EN = {"drop", "fall", "loss", "miss", "downgrade", "sell", "bearish", "crash",
              "decline", "weak", "underperform", "layoff", "debt", "warning"}


def _compute_article_sentiment(title: str, summary: str) -> float:
    """Simple keyword-based sentiment for FR + EN articles."""
    text = (title + " " + (summary or "")).lower()
    bull_count = sum(1 for w in (BULLISH_FR | BULLISH_EN) if w in text)
    bear_count = sum(1 for w in (BEARISH_FR | BEARISH_EN) if w in text)
    total = bull_count + bear_count
    if total == 0:
        return 0.0
    return (bull_count - bear_count) / total  # -1 to +1


@router.get("/rss/{ticker}")
async def get_rss_sentiment(ticker: str):
    """Get sentiment from RSS articles mentioning the ticker (last 48h)."""
    ticker = ticker.upper()
    names = TICKER_NAMES.get(ticker, [ticker.lower().split(".")[0]])

    if not MONGODB_URI:
        raise HTTPException(status_code=503, detail="MongoDB not configured")

    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        client = AsyncIOMotorClient(MONGODB_URI)
        db = client.market_intelligence
        collection = db.raw_articles

        cutoff = datetime.utcnow() - timedelta(hours=48)

        # Build regex pattern for ticker name matching
        pattern = "|".join(re.escape(n) for n in names)
        regex = re.compile(pattern, re.IGNORECASE)

        # Query articles mentioning the ticker
        cursor = collection.find(
            {
                "collected_at": {"$gte": cutoff},
                "$or": [
                    {"title": {"$regex": regex}},
                    {"summary": {"$regex": regex}},
                ],
            },
            {"title": 1, "summary": 1, "source_feed": 1, "category": 1, "language": 1, "published_at": 1},
        ).limit(50)

        articles = await cursor.to_list(length=50)
        client.close()

    except Exception as e:
        logger.error("MongoDB query failed for %s: %s", ticker, e)
        raise HTTPException(status_code=503, detail=f"MongoDB error: {e}")

    if not articles:
        return {
            "ticker": ticker,
            "sentiment_score": None,
            "article_count": 0,
            "label": "no_data",
            "sources": [],
        }

    # Compute sentiment from articles
    scores = []
    sources = set()
    for a in articles:
        score = _compute_article_sentiment(a.get("title", ""), a.get("summary", ""))
        scores.append(score)
        sources.add(a.get("source_feed", "unknown"))

    avg_score = sum(scores) / len(scores) if scores else 0.0
    label = "bullish" if avg_score > 0.1 else ("bearish" if avg_score < -0.1 else "neutral")

    return {
        "ticker": ticker,
        "sentiment_score": round(avg_score, 3),
        "article_count": len(articles),
        "label": label,
        "sources": list(sources),
        "period": "48h",
    }
