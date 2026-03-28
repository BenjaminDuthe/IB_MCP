"""Insider Trading Signal — detect recent insider buying/selling via yfinance."""

import asyncio
import logging
import os
from datetime import datetime, timedelta

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sentiment", tags=["Insider Signal"])

MARKET_DATA_URL = os.environ.get("MCP_MARKET_DATA_URL", "http://mcp_market_data:5003")

_cache: dict[str, tuple[dict, float]] = {}
CACHE_TTL = 86400  # 24h — Form 4 filings update daily


@router.get("/insider/{ticker}")
async def get_insider_signal(ticker: str):
    """Analyze recent insider transactions for buy/sell signal."""
    ticker = ticker.upper()
    now = datetime.utcnow().timestamp()

    if ticker in _cache:
        cached, ts = _cache[ticker]
        if now - ts < CACHE_TTL:
            return cached

    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        txns = await asyncio.to_thread(lambda: t.insider_transactions)
    except Exception as e:
        logger.error("Insider data failed for %s: %s", ticker, e)
        return {"ticker": ticker, "sentiment_score": None, "error": str(e)}

    if txns is None or (hasattr(txns, "empty") and txns.empty):
        result = {"ticker": ticker, "sentiment_score": None, "net_purchases": 0,
                  "buys": 0, "sells": 0, "label": "no_data", "transactions": []}
        _cache[ticker] = (result, now)
        return result

    # Filter last 90 days
    cutoff = datetime.utcnow() - timedelta(days=90)
    recent = []
    buys = 0
    sells = 0
    buy_value = 0
    sell_value = 0

    for _, row in txns.iterrows():
        start_date = row.get("Start Date")
        if start_date is None:
            continue
        if hasattr(start_date, "to_pydatetime"):
            start_date = start_date.to_pydatetime()
        if hasattr(start_date, "replace") and start_date.tzinfo:
            start_date = start_date.replace(tzinfo=None)
        if start_date < cutoff:
            continue

        text = str(row.get("Text", "") or row.get("Transaction", "")).lower()
        shares = abs(row.get("Shares", 0) or 0)
        value = abs(row.get("Value", 0) or 0)
        insider = row.get("Insider", "?")
        position = row.get("Position", "?")

        is_purchase = "purchase" in text or "buy" in text or "acquisition" in text
        is_sale = "sale" in text or "sell" in text or "disposition" in text

        if is_purchase:
            buys += 1
            buy_value += value if value > 0 else shares
        elif is_sale:
            sells += 1
            sell_value += value if value > 0 else shares

        recent.append({
            "insider": str(insider)[:30],
            "position": str(position)[:30],
            "date": start_date.strftime("%Y-%m-%d") if hasattr(start_date, "strftime") else str(start_date),
            "type": "buy" if is_purchase else ("sell" if is_sale else "other"),
            "shares": int(shares),
        })

    net_purchases = buys - sells

    # Score: insiders buying = bullish signal
    if net_purchases >= 3:
        score = 1.0
        label = "strong_buy"
    elif net_purchases >= 1:
        score = 0.5
        label = "buy"
    elif net_purchases <= -3:
        score = -0.5
        label = "sell"
    elif net_purchases <= -1:
        score = -0.2
        label = "mild_sell"
    else:
        score = 0.0
        label = "neutral"

    result = {
        "ticker": ticker,
        "sentiment_score": round(score, 3),
        "net_purchases": net_purchases,
        "buys": buys,
        "sells": sells,
        "label": label,
        "period": "90d",
        "transactions": recent[:10],
    }
    _cache[ticker] = (result, now)
    return result
