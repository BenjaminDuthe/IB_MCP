import os
import re
import logging
import praw
from prawcore.exceptions import ResponseException, OAuthException
from fastapi import APIRouter, HTTPException, Query
from textblob import TextBlob

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sentiment", tags=["Reddit Sentiment"])

SUBREDDITS = ["wallstreetbets", "stocks", "investing"]

# Module-level Reddit client cache
_reddit_client = None
_reddit_init_error = None


def _get_reddit_client():
    """Create a PRAW Reddit client from environment variables with validation."""
    global _reddit_client, _reddit_init_error

    # Return cached client or error
    if _reddit_client is not None:
        return _reddit_client
    if _reddit_init_error is not None:
        return None

    client_id = os.environ.get("REDDIT_CLIENT_ID")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
    user_agent = os.environ.get("REDDIT_USER_AGENT", "IB_MCP-Sentiment/1.0")

    if not client_id or not client_secret:
        _reddit_init_error = "Missing REDDIT_CLIENT_ID or REDDIT_CLIENT_SECRET"
        logger.warning(f"Reddit init skipped: {_reddit_init_error}")
        return None

    if client_id == "your_reddit_client_id" or client_secret == "your_reddit_client_secret":
        _reddit_init_error = "Reddit credentials are placeholder values"
        logger.warning(f"Reddit init skipped: {_reddit_init_error}")
        return None

    try:
        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
            timeout=10,
        )
        # Validate connection by checking read-only mode
        _ = reddit.read_only
        _reddit_client = reddit
        logger.info("Reddit client initialized successfully")
        return reddit
    except (ResponseException, OAuthException) as e:
        _reddit_init_error = f"Reddit OAuth failed: {e}"
        logger.error(_reddit_init_error)
        return None
    except Exception as e:
        _reddit_init_error = f"Reddit init failed: {e}"
        logger.error(_reddit_init_error)
        return None


def _analyze_sentiment(text: str) -> dict:
    """Analyze sentiment of text using TextBlob."""
    blob = TextBlob(text)
    polarity = blob.sentiment.polarity
    if polarity > 0.1:
        label = "bullish"
    elif polarity < -0.1:
        label = "bearish"
    else:
        label = "neutral"
    return {"polarity": round(polarity, 3), "label": label}


@router.get("/reddit/{ticker}")
async def get_reddit_sentiment(
    ticker: str,
    limit: int = Query(50, ge=10, le=200, description="Number of posts to analyze per subreddit"),
):
    """Get Reddit sentiment for a ticker from r/wallstreetbets, r/stocks, r/investing."""
    reddit = _get_reddit_client()
    if reddit is None:
        raise HTTPException(
            status_code=503,
            detail="Reddit API not configured. Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET.",
        )

    ticker_upper = ticker.upper()
    ticker_pattern = re.compile(r"\b" + re.escape(ticker_upper) + r"\b", re.IGNORECASE)

    all_posts = []
    total_polarity = 0.0
    bullish_count = 0
    bearish_count = 0
    neutral_count = 0

    try:
        for sub_name in SUBREDDITS:
            try:
                subreddit = reddit.subreddit(sub_name)
                for post in subreddit.hot(limit=limit):
                    text = f"{post.title} {post.selftext}"
                    if not ticker_pattern.search(text):
                        continue

                    sentiment = _analyze_sentiment(text)
                    total_polarity += sentiment["polarity"]

                    if sentiment["label"] == "bullish":
                        bullish_count += 1
                    elif sentiment["label"] == "bearish":
                        bearish_count += 1
                    else:
                        neutral_count += 1

                    all_posts.append({
                        "subreddit": sub_name,
                        "title": post.title[:200],
                        "score": post.score,
                        "num_comments": post.num_comments,
                        "sentiment": sentiment,
                        "url": f"https://reddit.com{post.permalink}",
                    })
            except Exception as sub_error:
                logger.warning(f"Error fetching from r/{sub_name}: {sub_error}")
                continue

        mention_count = len(all_posts)
        avg_sentiment = round(total_polarity / mention_count, 3) if mention_count > 0 else 0
        bullish_ratio = round(bullish_count / mention_count, 2) if mention_count > 0 else 0

        top_posts = sorted(all_posts, key=lambda x: x["score"], reverse=True)[:5]

        return {
            "ticker": ticker_upper,
            "source": "reddit",
            "subreddits": SUBREDDITS,
            "mention_count": mention_count,
            "avg_sentiment": avg_sentiment,
            "bullish_ratio": bullish_ratio,
            "breakdown": {
                "bullish": bullish_count,
                "bearish": bearish_count,
                "neutral": neutral_count,
            },
            "top_posts": top_posts,
        }
    except (ResponseException, OAuthException) as e:
        logger.error(f"Reddit API error for {ticker}: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"Reddit API error: {type(e).__name__}. Check credentials.",
        )
    except Exception as e:
        logger.error(f"Unexpected error fetching Reddit sentiment for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=f"Reddit error: {type(e).__name__}: {str(e)}")
