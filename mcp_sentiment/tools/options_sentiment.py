"""Options Flow Sentiment — put/call ratio as contrarian signal."""

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sentiment", tags=["Options Sentiment"])

_cache: dict[str, tuple[dict, float]] = {}
CACHE_TTL = 600  # 10 min — options data changes intraday

# EU tickers don't have US-style options chains
_EU_SUFFIXES = (".PA", ".DE", ".AS", ".SW", ".L")


@router.get("/options/{ticker}")
async def get_options_sentiment(ticker: str):
    """Analyze put/call ratio for sentiment signal."""
    ticker = ticker.upper()

    # Skip EU tickers (no meaningful options data on yfinance)
    if any(ticker.endswith(s) for s in _EU_SUFFIXES):
        return {"ticker": ticker, "sentiment_score": None, "skipped": "eu_ticker"}

    now = datetime.utcnow().timestamp()
    if ticker in _cache:
        cached, ts = _cache[ticker]
        if now - ts < CACHE_TTL:
            return cached

    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        expirations = await asyncio.to_thread(lambda: t.options)
    except Exception as e:
        logger.error("Options data failed for %s: %s", ticker, e)
        return {"ticker": ticker, "sentiment_score": None, "error": str(e)}

    if not expirations:
        result = {"ticker": ticker, "sentiment_score": None, "label": "no_options"}
        _cache[ticker] = (result, now)
        return result

    # Analyze the 3 nearest expirations
    total_call_oi = 0
    total_put_oi = 0
    total_call_vol = 0
    total_put_vol = 0

    try:
        for exp in expirations[:3]:
            chain = await asyncio.to_thread(lambda e=exp: t.option_chain(e))
            calls = chain.calls
            puts = chain.puts

            total_call_oi += calls["openInterest"].sum() if "openInterest" in calls.columns else 0
            total_put_oi += puts["openInterest"].sum() if "openInterest" in puts.columns else 0
            total_call_vol += calls["volume"].fillna(0).sum() if "volume" in calls.columns else 0
            total_put_vol += puts["volume"].fillna(0).sum() if "volume" in puts.columns else 0
    except Exception as e:
        logger.warning("Options chain parse failed for %s: %s", ticker, e)
        result = {"ticker": ticker, "sentiment_score": None, "error": str(e)}
        _cache[ticker] = (result, now)
        return result

    pc_ratio_oi = total_put_oi / total_call_oi if total_call_oi > 0 else 1.0
    pc_ratio_vol = total_put_vol / total_call_vol if total_call_vol > 0 else 1.0

    # Sentiment score based on put/call ratio
    # PC > 1.5 = extreme fear (contrarian buy)
    # PC < 0.5 = extreme greed (contrarian sell)
    # PC 0.7-1.3 = neutral
    pc = pc_ratio_oi  # OI is more reliable than volume
    if pc > 2.0:
        score = 0.5  # extreme fear = strong buy signal
        label = "extreme_fear"
    elif pc > 1.5:
        score = 0.3
        label = "fear"
    elif pc < 0.4:
        score = -0.4
        label = "extreme_greed"
    elif pc < 0.6:
        score = -0.2
        label = "greed"
    else:
        score = 0.0
        label = "neutral"

    result = {
        "ticker": ticker,
        "sentiment_score": round(score, 3),
        "put_call_ratio_oi": round(pc_ratio_oi, 3),
        "put_call_ratio_volume": round(pc_ratio_vol, 3),
        "total_call_oi": int(total_call_oi),
        "total_put_oi": int(total_put_oi),
        "expirations_analyzed": min(len(expirations), 3),
        "label": label,
    }
    _cache[ticker] = (result, now)
    return result
