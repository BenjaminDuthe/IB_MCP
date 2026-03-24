import asyncio
import json
import logging
import os
import uuid
from datetime import datetime

import httpx

from rss_collector.mongo_client import (
    get_unsent_articles,
    mark_articles_sent,
    store_intelligence,
)
from rss_collector.prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

_last_request_time: float = 0


def _format_articles_for_prompt(articles: list[dict]) -> str:
    """Format articles into a text prompt for OpenClaw."""
    lines = []
    for i, article in enumerate(articles, 1):
        text = article.get("full_text") or article.get("summary") or ""
        text = text[:1500]  # Limit per article
        lines.append(
            f"--- Article {i} ---\n"
            f"Source: {article['source_feed']} ({article['category']})\n"
            f"Title: {article['title']}\n"
            f"URL: {article['url']}\n"
            f"Published: {article.get('published_at', 'N/A')}\n"
            f"Content:\n{text}\n"
        )
    return "\n".join(lines)


async def _send_to_openclaw(articles: list[dict], batch_id: str) -> dict | None:
    """Send a batch of articles to OpenClaw /v1/responses."""
    global _last_request_time

    api_url = os.environ["OPENCLAW_API_URL"]
    token = os.environ["OPENCLAW_GATEWAY_TOKEN"]
    session_key = os.environ.get("OPENCLAW_SESSION_KEY", "rss-analyst")
    min_interval = int(os.environ.get("OPENCLAW_MIN_INTERVAL_SECONDS", "30"))

    # Rate limiting
    now = asyncio.get_event_loop().time()
    elapsed = now - _last_request_time
    if elapsed < min_interval:
        wait = min_interval - elapsed
        logger.info("Rate limiting: waiting %.1fs", wait)
        await asyncio.sleep(wait)

    prompt = _format_articles_for_prompt(articles)
    payload = {
        "model": "openclaw",
        "input": prompt,
        "instructions": SYSTEM_PROMPT,
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "x-openclaw-session-key": session_key,
    }

    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                _last_request_time = asyncio.get_event_loop().time()
                response = await client.post(api_url, json=payload, headers=headers)

                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429 or response.status_code >= 500:
                    wait = (2 ** attempt) * 10
                    logger.warning(
                        "OpenClaw returned %d, retrying in %ds (attempt %d/%d)",
                        response.status_code, wait, attempt + 1, max_retries,
                    )
                    await asyncio.sleep(wait)
                else:
                    logger.error(
                        "OpenClaw error %d: %s", response.status_code, response.text[:500]
                    )
                    return None
        except httpx.TimeoutException:
            wait = (2 ** attempt) * 15
            logger.warning("OpenClaw timeout, retrying in %ds", wait)
            await asyncio.sleep(wait)
        except Exception as e:
            logger.error("OpenClaw request failed: %s", e)
            return None

    logger.error("OpenClaw: all %d retries exhausted", max_retries)
    return None


def _parse_intelligence(response_data: dict, batch_id: str, articles: list[dict]) -> dict | None:
    """Parse OpenClaw response into MarketIntelligence format."""
    try:
        # Extract the text content from the response
        output_text = ""
        if isinstance(response_data, dict):
            # OpenClaw responses format
            output = response_data.get("output", [])
            if isinstance(output, list):
                for item in output:
                    if isinstance(item, dict) and item.get("type") == "message":
                        for content in item.get("content", []):
                            if isinstance(content, dict) and content.get("type") == "output_text":
                                output_text = content.get("text", "")
                                break
            elif isinstance(output, str):
                output_text = output
            # Fallback: try direct text field
            if not output_text:
                output_text = response_data.get("text", "") or response_data.get("content", "")

        if not output_text:
            logger.warning("No text content in OpenClaw response")
            return None

        # Try to parse JSON from the response
        # Strip markdown code fences if present
        text = output_text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        parsed = json.loads(text)

        return {
            "batch_id": batch_id,
            "processed_at": datetime.utcnow(),
            "articles_count": len(articles),
            "article_url_hashes": [a["url_hash"] for a in articles],
            "tickers_mentioned": parsed.get("tickers_mentioned", []),
            "events": parsed.get("events", []),
            "sentiment_summary": parsed.get("sentiment_summary", {}),
            "key_insights": parsed.get("key_insights", []),
            "risk_alerts": parsed.get("risk_alerts", []),
            "sector_impacts": parsed.get("sector_impacts", []),
            "raw_response": output_text[:10000],
        }
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse OpenClaw JSON response: %s", e)
        # Store raw response even if parsing fails
        return {
            "batch_id": batch_id,
            "processed_at": datetime.utcnow(),
            "articles_count": len(articles),
            "article_url_hashes": [a["url_hash"] for a in articles],
            "tickers_mentioned": [],
            "events": [],
            "sentiment_summary": {},
            "key_insights": [],
            "risk_alerts": [],
            "sector_impacts": [],
            "raw_response": output_text[:10000],
        }
    except Exception as e:
        logger.error("Failed to parse intelligence: %s", e)
        return None


async def run_openclaw_push() -> dict:
    """Fetch unsent articles and push batches to OpenClaw."""
    batch_size = int(os.environ.get("OPENCLAW_BATCH_SIZE", "7"))
    unsent = await get_unsent_articles(limit=batch_size * 5)

    if not unsent:
        logger.info("No unsent articles to push")
        return {"batches_sent": 0, "articles_sent": 0, "intelligence_stored": 0}

    logger.info("Found %d unsent articles", len(unsent))

    batches_sent = 0
    articles_sent = 0
    intelligence_stored = 0

    # Process in batches
    for i in range(0, len(unsent), batch_size):
        batch = unsent[i:i + batch_size]
        batch_id = str(uuid.uuid4())[:12]

        logger.info("Sending batch %s (%d articles)", batch_id, len(batch))
        response = await _send_to_openclaw(batch, batch_id)

        if response:
            url_hashes = [a["url_hash"] for a in batch]
            await mark_articles_sent(url_hashes, batch_id)
            batches_sent += 1
            articles_sent += len(batch)

            intelligence = _parse_intelligence(response, batch_id, batch)
            if intelligence:
                await store_intelligence(intelligence)
                intelligence_stored += 1
                logger.info(
                    "Batch %s: %d tickers, %d events, %d insights",
                    batch_id,
                    len(intelligence.get("tickers_mentioned", [])),
                    len(intelligence.get("events", [])),
                    len(intelligence.get("key_insights", [])),
                )
        else:
            logger.warning("Batch %s failed, stopping push cycle", batch_id)
            break

    stats = {
        "batches_sent": batches_sent,
        "articles_sent": articles_sent,
        "intelligence_stored": intelligence_stored,
    }
    logger.info("Push cycle complete: %s", stats)
    return stats
