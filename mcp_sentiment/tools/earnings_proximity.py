"""Earnings Proximity — detect upcoming earnings dates via yfinance."""

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sentiment", tags=["Earnings Proximity"])

# Cache: ticker → (result, timestamp)
_cache: dict[str, tuple[dict, float]] = {}
CACHE_TTL = 3600  # 1h — earnings dates are fixed, rarely change intraday


@router.get("/earnings/{ticker}")
async def get_earnings_proximity(ticker: str):
    """Check if earnings are coming soon for a ticker."""
    ticker = ticker.upper()
    now = datetime.now(timezone.utc).timestamp()

    if ticker in _cache:
        cached, ts = _cache[ticker]
        if now - ts < CACHE_TTL:
            return cached

    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        cal = await asyncio.to_thread(lambda: t.calendar)
    except Exception as e:
        logger.error("yfinance calendar failed for %s: %s", ticker, e)
        return {"ticker": ticker, "earnings_date": None, "error": str(e)}

    earnings_date = None
    days_to_earnings = None

    if cal is not None:
        # yfinance returns dict or DataFrame depending on version
        if isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            if isinstance(ed, list) and ed:
                earnings_date = ed[0]
            elif isinstance(ed, datetime):
                earnings_date = ed
        else:
            # DataFrame format
            try:
                if hasattr(cal, "loc") and "Earnings Date" in cal.index:
                    val = cal.loc["Earnings Date"]
                    if hasattr(val, "iloc"):
                        earnings_date = val.iloc[0]
                    else:
                        earnings_date = val
            except Exception:
                pass

    if earnings_date is not None:
        if isinstance(earnings_date, str):
            try:
                earnings_date = datetime.fromisoformat(earnings_date)
            except ValueError:
                earnings_date = None

        if earnings_date is not None:
            # Convert date to datetime if needed (yfinance returns date, not datetime)
            import datetime as dt_module
            if isinstance(earnings_date, dt_module.date) and not isinstance(earnings_date, datetime):
                earnings_date = datetime(earnings_date.year, earnings_date.month, earnings_date.day, tzinfo=timezone.utc)
            elif hasattr(earnings_date, "tzinfo") and earnings_date.tzinfo is None:
                earnings_date = earnings_date.replace(tzinfo=timezone.utc)
            delta = earnings_date - datetime.now(timezone.utc)
            days_to_earnings = delta.days

    earnings_imminent = days_to_earnings is not None and 0 <= days_to_earnings <= 7

    result = {
        "ticker": ticker,
        "earnings_date": earnings_date.isoformat() if earnings_date else None,
        "days_to_earnings": days_to_earnings,
        "earnings_imminent": earnings_imminent,
        "confidence_modifier": 0.7 if earnings_imminent else 1.0,
    }
    _cache[ticker] = (result, now)
    return result
