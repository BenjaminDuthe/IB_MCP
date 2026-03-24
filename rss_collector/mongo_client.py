import logging
import os
from datetime import datetime

from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)

_client: AsyncIOMotorClient | None = None
_db = None


async def get_db():
    global _client, _db
    if _db is None:
        uri = os.environ["MONGODB_URI"]
        db_name = os.environ.get("MONGODB_DATABASE", "market_intelligence")
        _client = AsyncIOMotorClient(uri)
        _db = _client[db_name]
        logger.info("Connected to MongoDB database: %s", db_name)
    return _db


async def close_db():
    global _client, _db
    if _client:
        _client.close()
        _client = None
        _db = None
        logger.info("MongoDB connection closed")


async def insert_articles(articles: list[dict]) -> int:
    db = await get_db()
    if not articles:
        return 0
    try:
        result = await db.raw_articles.insert_many(articles, ordered=False)
        return len(result.inserted_ids)
    except Exception as e:
        # BulkWriteError with duplicates is expected
        if "duplicate key" in str(e).lower() or "E11000" in str(e):
            # Count how many were actually inserted
            inserted = getattr(getattr(e, "details", None), "get", lambda *a: 0)("nInserted", 0)
            if hasattr(e, "details") and isinstance(e.details, dict):
                inserted = e.details.get("nInserted", 0)
            logger.info("Bulk insert: %d new articles (duplicates skipped)", inserted)
            return inserted
        raise


async def get_unsent_articles(limit: int = 50) -> list[dict]:
    db = await get_db()
    cursor = db.raw_articles.find(
        {"sent_to_openclaw": False},
        sort=[("collected_at", -1)],
    ).limit(limit)
    return await cursor.to_list(length=limit)


async def mark_articles_sent(url_hashes: list[str], batch_id: str):
    db = await get_db()
    await db.raw_articles.update_many(
        {"url_hash": {"$in": url_hashes}},
        {"$set": {"sent_to_openclaw": True, "openclaw_batch_id": batch_id}},
    )


async def store_intelligence(intelligence: dict):
    db = await get_db()
    await db.market_intelligence.insert_one(intelligence)


async def log_pipeline_run(run_type: str, stats: dict):
    db = await get_db()
    await db.pipeline_runs.insert_one({
        "run_type": run_type,
        "started_at": datetime.utcnow(),
        **stats,
    })


async def get_stats() -> dict:
    db = await get_db()
    total_articles = await db.raw_articles.count_documents({})
    unsent = await db.raw_articles.count_documents({"sent_to_openclaw": False})
    total_intelligence = await db.market_intelligence.count_documents({})
    total_runs = await db.pipeline_runs.count_documents({})

    last_collection = await db.pipeline_runs.find_one(
        {"run_type": "collection"}, sort=[("started_at", -1)]
    )
    last_push = await db.pipeline_runs.find_one(
        {"run_type": "openclaw_push"}, sort=[("started_at", -1)]
    )

    return {
        "total_articles": total_articles,
        "unsent_articles": unsent,
        "total_intelligence_records": total_intelligence,
        "total_pipeline_runs": total_runs,
        "last_collection": last_collection["started_at"].isoformat() if last_collection else None,
        "last_push": last_push["started_at"].isoformat() if last_push else None,
    }
