import asyncio
import hashlib
import logging
import socket
from datetime import datetime

import feedparser

from rss_collector.feeds import FEEDS
from rss_collector.models import FeedConfig
from rss_collector.mongo_client import insert_articles, get_db

# Set global socket timeout for feedparser (which uses urllib internally)
socket.setdefaulttimeout(15)

logger = logging.getLogger(__name__)

_scrape_semaphore = asyncio.Semaphore(10)

# Track consecutive failures per feed
_feed_failures: dict[str, int] = {}


def _hash_url(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


_USER_AGENT = "Mozilla/5.0 (compatible; RSSCollector/1.0; +https://sitecraft-it.com)"


def _parse_feed_sync(feed: FeedConfig, limit: int = 50) -> list[dict]:
    """Parse a single RSS feed synchronously. Returns None on hard failure, [] on empty."""
    try:
        parsed = feedparser.parse(
            feed.url,
            request_headers={"User-Agent": _USER_AGENT},
        )
        articles = []
        for entry in parsed.entries[:limit]:
            url = entry.get("link", "")
            if not url:
                continue
            published = None
            if entry.get("published_parsed"):
                try:
                    published = datetime(*entry.published_parsed[:6])
                except Exception:
                    pass
            articles.append({
                "url_hash": _hash_url(url),
                "url": url,
                "title": entry.get("title", "")[:500],
                "summary": (entry.get("summary", "") or "")[:500],
                "full_text": None,
                "source_feed": feed.name,
                "category": feed.category,
                "language": feed.language,
                "published_at": published,
                "collected_at": datetime.utcnow(),
                "sent_to_openclaw": False,
                "openclaw_batch_id": None,
            })
        return articles
    except Exception as e:
        logger.warning("Failed to parse feed %s: %s", feed.name, e)
        return None  # None = hard failure, [] = empty feed


async def _scrape_full_text(url: str, timeout: float = 10.0) -> str | None:
    """Scrape full article text using newspaper4k."""
    async with _scrape_semaphore:
        try:
            import newspaper
            article = await asyncio.to_thread(
                _scrape_article_sync, url, timeout
            )
            return article
        except Exception as e:
            logger.debug("Scrape failed for %s: %s", url, e)
            return None


def _scrape_article_sync(url: str, timeout: float) -> str | None:
    import newspaper
    try:
        article = newspaper.Article(url, request_timeout=timeout)
        article.download()
        article.parse()
        if article.text and len(article.text) > 50:
            return article.text[:5000]
    except Exception:
        pass
    return None


async def _filter_new_articles(articles: list[dict]) -> list[dict]:
    """Remove articles that already exist in MongoDB."""
    if not articles:
        return []
    db = await get_db()
    url_hashes = [a["url_hash"] for a in articles]
    existing = await db.raw_articles.find(
        {"url_hash": {"$in": url_hashes}},
        {"url_hash": 1},
    ).to_list(length=len(url_hashes))
    existing_hashes = {doc["url_hash"] for doc in existing}
    return [a for a in articles if a["url_hash"] not in existing_hashes]


async def run_collection_cycle() -> dict:
    """Fetch all RSS feeds, dedup, scrape, and store."""
    logger.info("Starting collection cycle for %d feeds", len(FEEDS))
    start = datetime.utcnow()

    # Fetch all feeds in parallel
    tasks = [asyncio.to_thread(_parse_feed_sync, feed) for feed in FEEDS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_articles = []
    feeds_ok = 0
    feeds_empty = 0
    feeds_failed = 0
    for feed, result in zip(FEEDS, results):
        if isinstance(result, Exception):
            feeds_failed += 1
            _feed_failures[feed.name] = _feed_failures.get(feed.name, 0) + 1
            if _feed_failures[feed.name] >= 5:
                logger.warning("Feed %s has failed %d consecutive times", feed.name, _feed_failures[feed.name])
            continue
        if result is None:
            feeds_failed += 1
            _feed_failures[feed.name] = _feed_failures.get(feed.name, 0) + 1
            continue
        _feed_failures[feed.name] = 0
        if result:
            feeds_ok += 1
            all_articles.extend(result)
        else:
            feeds_empty += 1

    logger.info("Fetched %d articles from %d feeds (%d empty, %d failed)", len(all_articles), feeds_ok, feeds_empty, feeds_failed)

    # Dedup against MongoDB
    new_articles = await _filter_new_articles(all_articles)
    logger.info("After dedup: %d new articles", len(new_articles))

    # Scrape full text for new articles
    if new_articles:
        scrape_tasks = [_scrape_full_text(a["url"]) for a in new_articles]
        scrape_results = await asyncio.gather(*scrape_tasks)
        for article, full_text in zip(new_articles, scrape_results):
            article["full_text"] = full_text

        # Store in MongoDB
        inserted = await insert_articles(new_articles)
        logger.info("Inserted %d new articles into MongoDB", inserted)
    else:
        inserted = 0

    stats = {
        "feeds_total": len(FEEDS),
        "feeds_ok": feeds_ok,
        "feeds_empty": feeds_empty,
        "feeds_failed": feeds_failed,
        "articles_fetched": len(all_articles),
        "articles_new": len(new_articles),
        "articles_inserted": inserted,
        "duration_seconds": (datetime.utcnow() - start).total_seconds(),
        "failing_feeds": [
            name for name, count in _feed_failures.items() if count >= 5
        ],
    }
    logger.info("Collection cycle complete: %s", stats)
    return stats
