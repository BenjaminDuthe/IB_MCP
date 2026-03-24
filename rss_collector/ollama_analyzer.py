"""Local Ollama replacement for openclaw_client.py.

Same interface: takes unsent articles, analyzes them via local LLM,
stores MarketIntelligence in MongoDB. Zero Claude API tokens.
"""

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

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://192.168.1.120:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")


def _format_articles_for_prompt(articles: list[dict]) -> str:
    """Format articles into a text prompt (same as openclaw_client)."""
    lines = []
    for i, article in enumerate(articles, 1):
        text = article.get("full_text") or article.get("summary") or ""
        text = text[:1500]
        lines.append(
            f"--- Article {i} ---\n"
            f"Source: {article['source_feed']} ({article['category']})\n"
            f"Title: {article['title']}\n"
            f"URL: {article['url']}\n"
            f"Published: {article.get('published_at', 'N/A')}\n"
            f"Content:\n{text}\n"
        )
    return "\n".join(lines)


async def _send_to_ollama(articles: list[dict], batch_id: str) -> dict | None:
    """Send a batch of articles to Ollama for analysis."""
    prompt = _format_articles_for_prompt(articles)

    max_retries = 2
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{OLLAMA_URL}/api/generate",
                    json={
                        "model": OLLAMA_MODEL,
                        "system": SYSTEM_PROMPT,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"num_predict": 1024, "temperature": 0.2},
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return {"text": data.get("response", "")}
                logger.warning(
                    "Ollama returned %d (attempt %d/%d)",
                    resp.status_code, attempt + 1, max_retries,
                )
        except httpx.TimeoutException:
            logger.warning("Ollama timeout (attempt %d/%d)", attempt + 1, max_retries)
        except Exception as e:
            logger.error("Ollama request failed: %s", e)
            return None

        if attempt < max_retries - 1:
            await asyncio.sleep(5)

    logger.error("Ollama: all %d retries exhausted for batch %s", max_retries, batch_id)
    return None


def _parse_intelligence(response_data: dict, batch_id: str, articles: list[dict]) -> dict | None:
    """Parse Ollama response into MarketIntelligence format."""
    try:
        output_text = response_data.get("text", "")
        if not output_text:
            logger.warning("No text content in Ollama response")
            return None

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
            "source": "ollama",
        }
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse Ollama JSON: %s", e)
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
            "source": "ollama",
        }
    except Exception as e:
        logger.error("Failed to parse intelligence: %s", e)
        return None


async def run_ollama_push() -> dict:
    """Fetch unsent articles and analyze via local Ollama. Drop-in replacement for run_openclaw_push."""
    batch_size = int(os.environ.get("OLLAMA_BATCH_SIZE", os.environ.get("OPENCLAW_BATCH_SIZE", "7")))
    unsent = await get_unsent_articles(limit=batch_size * 5)

    if not unsent:
        logger.info("No unsent articles to analyze")
        return {"batches_sent": 0, "articles_sent": 0, "intelligence_stored": 0}

    logger.info("Found %d unsent articles for Ollama analysis", len(unsent))

    batches_sent = 0
    articles_sent = 0
    intelligence_stored = 0

    for i in range(0, len(unsent), batch_size):
        batch = unsent[i:i + batch_size]
        batch_id = str(uuid.uuid4())[:12]

        logger.info("Analyzing batch %s (%d articles) via Ollama", batch_id, len(batch))
        response = await _send_to_ollama(batch, batch_id)

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
    logger.info("Ollama push cycle complete: %s", stats)
    return stats
