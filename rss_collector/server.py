import asyncio
import logging
import os
from contextlib import asynccontextmanager

import httpx
import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from rss_collector.collector import run_collection_cycle
from rss_collector.mongo_client import close_db, get_stats, log_pipeline_run
from rss_collector.ollama_analyzer import run_ollama_push

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def _collection_job():
    try:
        stats = await run_collection_cycle()
        await log_pipeline_run("collection", stats)
    except (httpx.HTTPError, asyncio.TimeoutError) as e:
        logger.error("Collection cycle failed (network): %s", e)
    except Exception as e:
        logger.error("Collection cycle failed (unexpected): %s", e, exc_info=True)


async def _push_job():
    try:
        stats = await run_ollama_push()
        await log_pipeline_run("ollama_push", stats)
    except (httpx.HTTPError, asyncio.TimeoutError) as e:
        logger.error("Ollama push failed (network): %s", e)
    except Exception as e:
        logger.error("Ollama push failed (unexpected): %s", e, exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    collect_interval = int(os.environ.get("RSS_COLLECT_INTERVAL_MINUTES", "15"))
    push_interval = int(os.environ.get("RSS_PUSH_INTERVAL_MINUTES", "20"))

    scheduler.add_job(_collection_job, "interval", minutes=collect_interval, id="collection")
    scheduler.add_job(_push_job, "interval", minutes=push_interval, id="push")
    scheduler.start()
    logger.info(
        "Scheduler started: collection every %dm, push every %dm",
        collect_interval, push_interval,
    )

    # Schedule first collection as background task (non-blocking startup)
    import asyncio
    asyncio.create_task(_collection_job())

    yield

    scheduler.shutdown(wait=False)
    await close_db()
    logger.info("Shutdown complete")


app = FastAPI(
    title="RSS Financial Collector",
    description="Collects financial RSS feeds and analyzes via local Ollama LLM",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "rss-collector"}


@app.get("/status")
async def status():
    try:
        stats = await get_stats()
        return {"status": "ok", **stats}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.post("/collect")
async def trigger_collection():
    """Manually trigger a collection cycle."""
    stats = await run_collection_cycle()
    await log_pipeline_run("collection", stats)
    return stats


@app.post("/push")
async def trigger_push():
    """Manually trigger an Ollama analysis cycle."""
    stats = await run_ollama_push()
    await log_pipeline_run("ollama_push", stats)
    return stats


if __name__ == "__main__":
    host = os.environ.get("RSS_COLLECTOR_HOST", "0.0.0.0")
    port = int(os.environ.get("RSS_COLLECTOR_PORT", "5020"))
    uvicorn.run(app, host=host, port=port, log_level="info")
