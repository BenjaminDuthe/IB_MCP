"""Google Trends — detect unusual search interest spikes for tickers."""

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sentiment", tags=["Google Trends"])

# Cache: ticker → (result, timestamp)
_cache: dict[str, tuple[dict, float]] = {}
CACHE_TTL = 1800  # 30 min — trends are weekly data, no need to refresh faster

# Map tickers to search terms (company names work better than symbols)
TICKER_SEARCH_TERMS = {
    "NVDA": "NVIDIA stock", "MSFT": "Microsoft stock", "GOOGL": "Google stock",
    "AMZN": "Amazon stock", "META": "Meta stock", "AAPL": "Apple stock",
    "TSLA": "Tesla stock", "AMD": "AMD stock", "NFLX": "Netflix stock",
    "AVGO": "Broadcom stock", "INTC": "Intel stock", "BA": "Boeing stock",
    "JPM": "JPMorgan stock", "V": "Visa stock", "XOM": "Exxon stock",
    "MC.PA": "LVMH action", "BNP.PA": "BNP Paribas action",
    "AIR.PA": "Airbus action", "TTE.PA": "TotalEnergies action",
    "SAP.DE": "SAP Aktie", "SIE.DE": "Siemens Aktie",
    "ASML.AS": "ASML stock", "NESN.SW": "Nestle stock",
}


@router.get("/trends/{ticker}")
async def get_google_trends(ticker: str):
    """Get Google Trends interest for a ticker over the last 7 days."""
    ticker = ticker.upper()
    now = datetime.utcnow().timestamp()

    if ticker in _cache:
        cached, ts = _cache[ticker]
        if now - ts < CACHE_TTL:
            return cached

    search_term = TICKER_SEARCH_TERMS.get(ticker, f"{ticker} stock")

    try:
        from pytrends.request import TrendReq
        pytrends = await asyncio.to_thread(lambda: TrendReq(hl="en-US", tz=0, timeout=(5, 10)))
        await asyncio.to_thread(lambda: pytrends.build_payload([search_term], timeframe="now 7-d"))
        df = await asyncio.to_thread(lambda: pytrends.interest_over_time())
    except Exception as e:
        logger.warning("Google Trends failed for %s: %s", ticker, e)
        result = {
            "ticker": ticker,
            "sentiment_score": None,
            "search_term": search_term,
            "error": str(e),
        }
        _cache[ticker] = (result, now)
        return result

    if df is None or df.empty or search_term not in df.columns:
        result = {
            "ticker": ticker,
            "sentiment_score": None,
            "search_term": search_term,
            "interest_current": None,
            "interest_avg": None,
            "spike": False,
        }
        _cache[ticker] = (result, now)
        return result

    values = df[search_term].values
    current = float(values[-1]) if len(values) > 0 else 0
    avg = float(values.mean()) if len(values) > 0 else 0

    # Spike detection: current > 2x average = unusual interest
    spike = current > avg * 2.0 if avg > 5 else False
    spike_ratio = current / avg if avg > 0 else 1.0

    # Convert to sentiment score: spike = mild positive (attention ≠ direction)
    # But unusual spikes often precede moves
    if spike:
        sentiment_score = round(min((spike_ratio - 1) * 0.3, 0.5), 3)
    else:
        sentiment_score = 0.0

    result = {
        "ticker": ticker,
        "sentiment_score": sentiment_score,
        "search_term": search_term,
        "interest_current": round(current, 1),
        "interest_avg": round(avg, 1),
        "spike": spike,
        "spike_ratio": round(spike_ratio, 2),
    }
    _cache[ticker] = (result, now)
    return result
