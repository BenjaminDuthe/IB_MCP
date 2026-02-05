import os
import finnhub
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/news", tags=["Finnhub News"])


def _get_finnhub_client():
    """Create a Finnhub client from environment variable."""
    api_key = os.environ.get("FINNHUB_API_KEY")
    if not api_key:
        return None
    return finnhub.Client(api_key=api_key)


@router.get("/stock/{ticker}")
async def get_stock_news(
    ticker: str,
    days: int = Query(7, ge=1, le=30, description="Number of days to look back"),
):
    """Get recent news articles for a specific stock ticker from Finnhub."""
    client = _get_finnhub_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Finnhub API not configured. Set FINNHUB_API_KEY.")

    try:
        today = datetime.now()
        from_date = (today - timedelta(days=days)).strftime("%Y-%m-%d")
        to_date = today.strftime("%Y-%m-%d")

        news = client.company_news(ticker.upper(), _from=from_date, to=to_date)

        articles = []
        for item in news[:20]:
            articles.append({
                "headline": item.get("headline"),
                "summary": item.get("summary", "")[:300],
                "source": item.get("source"),
                "url": item.get("url"),
                "datetime": datetime.fromtimestamp(item.get("datetime", 0)).isoformat(),
                "category": item.get("category"),
                "related": item.get("related"),
            })

        return {
            "ticker": ticker.upper(),
            "period": f"{from_date} to {to_date}",
            "article_count": len(articles),
            "articles": articles,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/market")
async def get_market_news(
    category: str = Query("general", description="Category: general, forex, crypto, merger"),
):
    """Get general market news from Finnhub by category."""
    client = _get_finnhub_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Finnhub API not configured. Set FINNHUB_API_KEY.")

    try:
        news = client.general_news(category, min_id=0)

        articles = []
        for item in news[:20]:
            articles.append({
                "headline": item.get("headline"),
                "summary": item.get("summary", "")[:300],
                "source": item.get("source"),
                "url": item.get("url"),
                "datetime": datetime.fromtimestamp(item.get("datetime", 0)).isoformat(),
                "category": item.get("category"),
            })

        return {
            "category": category,
            "article_count": len(articles),
            "articles": articles,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
