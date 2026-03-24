from datetime import datetime

from pydantic import BaseModel, Field


class FeedConfig(BaseModel):
    name: str
    url: str
    category: str
    language: str = "en"


class RawArticle(BaseModel):
    url_hash: str
    url: str
    title: str
    summary: str = ""
    full_text: str | None = None
    source_feed: str
    category: str
    language: str = "en"
    published_at: datetime | None = None
    collected_at: datetime = Field(default_factory=datetime.utcnow)
    sent_to_openclaw: bool = False
    openclaw_batch_id: str | None = None


class MarketIntelligence(BaseModel):
    batch_id: str
    processed_at: datetime
    articles_count: int
    article_url_hashes: list[str]
    tickers_mentioned: list[str] = []
    events: list[dict] = []
    sentiment_summary: dict = {}
    key_insights: list[str] = []
    risk_alerts: list[str] = []
    sector_impacts: list[dict] = []
    raw_response: str = ""
