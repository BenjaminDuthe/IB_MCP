import os
from fastapi import APIRouter, HTTPException, Query
import feedparser

router = APIRouter(prefix="/news", tags=["RSS Feeds"])

DEFAULT_FEEDS = [
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=AAPL&region=US&lang=en-US",
    "https://www.investing.com/rss/news.rss",
    "https://feeds.marketwatch.com/marketwatch/topstories/",
]


@router.get("/rss")
async def get_rss_feeds(
    limit: int = Query(20, ge=5, le=50, description="Number of articles per feed"),
):
    """Aggregate financial news from RSS feeds."""
    feeds_env = os.environ.get("RSS_FEEDS")
    if feeds_env:
        feed_urls = [url.strip() for url in feeds_env.split(",") if url.strip()]
    else:
        feed_urls = DEFAULT_FEEDS

    all_articles = []

    for url in feed_urls:
        try:
            feed = feedparser.parse(url)
            feed_title = feed.feed.get("title", url)

            for entry in feed.entries[:limit]:
                all_articles.append({
                    "feed": feed_title,
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", "")[:300],
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                })
        except Exception as e:
            all_articles.append({
                "feed": url,
                "error": str(e),
            })

    return {
        "feed_count": len(feed_urls),
        "article_count": len(all_articles),
        "articles": all_articles,
    }
