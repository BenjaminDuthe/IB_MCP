import asyncio
import os
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Query
import feedparser

router = APIRouter(prefix="/news", tags=["RSS Feeds"])

# RSS cache (TTL: 120 seconds)
_rss_cache: dict = {}
RSS_CACHE_TTL = 120

DEFAULT_FEEDS = [
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=AAPL&region=US&lang=en-US",
    "https://www.investing.com/rss/news.rss",
    "https://feeds.marketwatch.com/marketwatch/topstories/",
]


def _parse_feed(url: str, limit: int) -> list[dict]:
    """Parse a single RSS feed synchronously."""
    try:
        feed = feedparser.parse(url)
        feed_title = feed.feed.get("title", url)
        articles = []
        for entry in feed.entries[:limit]:
            articles.append({
                "feed": feed_title,
                "title": entry.get("title", ""),
                "summary": entry.get("summary", "")[:300],
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
            })
        return articles
    except Exception as e:
        return [{"feed": url, "error": str(e)}]


@router.get("/rss")
async def get_rss_feeds(
    limit: int = Query(20, ge=5, le=50, description="Number of articles per feed"),
):
    """Aggregate financial news from RSS feeds."""
    cache_key = f"rss:{limit}"
    if cache_key in _rss_cache:
        entry = _rss_cache[cache_key]
        if datetime.now() < entry["expires_at"]:
            return entry["data"]
        del _rss_cache[cache_key]

    feeds_env = os.environ.get("RSS_FEEDS")
    if feeds_env:
        feed_urls = [url.strip() for url in feeds_env.split(",") if url.strip()]
    else:
        feed_urls = DEFAULT_FEEDS

    # Fetch all feeds in parallel using thread pool
    results = await asyncio.gather(
        *[asyncio.to_thread(_parse_feed, url, limit) for url in feed_urls]
    )

    all_articles = []
    for articles in results:
        all_articles.extend(articles)

    result = {
        "feed_count": len(feed_urls),
        "article_count": len(all_articles),
        "articles": all_articles,
    }
    _rss_cache[cache_key] = {
        "data": result,
        "expires_at": datetime.now() + timedelta(seconds=RSS_CACHE_TTL),
    }
    return result
