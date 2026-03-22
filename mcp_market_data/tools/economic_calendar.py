"""Economic calendar, earnings calendar, and IPO calendar via Finnhub API."""

import asyncio
import os
from datetime import datetime, timedelta

import finnhub
from finnhub.exceptions import FinnhubAPIException
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(tags=["Economic Calendar"])

# --------------- Finnhub client singleton ---------------

_finnhub_client = None


def _get_finnhub_client():
    global _finnhub_client
    if _finnhub_client is None:
        api_key = os.environ.get("FINNHUB_API_KEY")
        if not api_key:
            return None
        _finnhub_client = finnhub.Client(api_key=api_key)
    return _finnhub_client


# --------------- Cache ---------------

_cache = {}
CACHE_TTL_CALENDAR = 3600   # 1h for economic calendar
CACHE_TTL_EARNINGS = 14400  # 4h for earnings/IPO


def _get_cached(key: str) -> dict | None:
    if key in _cache:
        entry = _cache[key]
        if datetime.now() < entry["expires_at"]:
            return entry["data"]
        del _cache[key]
    return None


def _set_cache(key: str, data: dict, ttl: int = CACHE_TTL_CALENDAR) -> None:
    _cache[key] = {"data": data, "expires_at": datetime.now() + timedelta(seconds=ttl)}


# --------------- Sync data fetchers ---------------

def _fetch_economic_calendar(days_ahead: int) -> dict:
    client = _get_finnhub_client()
    if client is None:
        raise ValueError("FINNHUB_API_KEY not configured")

    from_date = datetime.now().strftime("%Y-%m-%d")
    to_date = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    try:
        raw = client.calendar_economic(_from=from_date, to=to_date)
    except FinnhubAPIException as e:
        if "403" in str(e):
            return {
                "events": [],
                "total": 0,
                "period": f"{from_date} to {to_date}",
                "next_high_impact": None,
                "error": "Economic calendar requires Finnhub premium plan. Earnings and IPO calendars are available on free tier.",
            }
        raise
    events_raw = raw.get("economicCalendar", []) if isinstance(raw, dict) else []

    # Filter US + high/medium impact
    events = []
    for ev in events_raw:
        country = ev.get("country", "")
        impact = (ev.get("impact") or "").lower()
        if country != "US" or impact not in ("high", "medium"):
            continue
        events.append({
            "date": ev.get("date", ""),
            "time": ev.get("time", ""),
            "event": ev.get("event", ""),
            "impact": impact,
            "previous": ev.get("prev"),
            "forecast": ev.get("estimate"),
            "actual": ev.get("actual"),
            "unit": ev.get("unit", ""),
        })

    events.sort(key=lambda x: x["date"])

    # Next high-impact event
    next_high = None
    today = datetime.now().date()
    for ev in events:
        if ev["impact"] == "high" and ev["date"]:
            try:
                ev_date = datetime.strptime(ev["date"], "%Y-%m-%d").date()
                diff = (ev_date - today).days
                next_high = f"{ev['event']} in {diff} day{'s' if diff != 1 else ''}"
                break
            except ValueError:
                continue

    return {
        "events": events,
        "total": len(events),
        "period": f"{from_date} to {to_date}",
        "next_high_impact": next_high,
    }


def _fetch_earnings_calendar(days_ahead: int) -> dict:
    client = _get_finnhub_client()
    if client is None:
        raise ValueError("FINNHUB_API_KEY not configured")

    from_date = datetime.now().strftime("%Y-%m-%d")
    to_date = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    raw = client.earnings_calendar(_from=from_date, to=to_date, symbol="", international=False)
    earnings_raw = raw.get("earningsCalendar", []) if isinstance(raw, dict) else []

    earnings = []
    for er in earnings_raw:
        earnings.append({
            "date": er.get("date", ""),
            "symbol": er.get("symbol", ""),
            "hour": er.get("hour", ""),  # bmo=before market open, amc=after market close
            "eps_estimate": er.get("epsEstimate"),
            "eps_actual": er.get("epsActual"),
            "revenue_estimate": er.get("revenueEstimate"),
            "revenue_actual": er.get("revenueActual"),
            "quarter": er.get("quarter"),
            "year": er.get("year"),
        })

    earnings.sort(key=lambda x: (x["date"], x["symbol"]))

    return {
        "earnings": earnings,
        "total": len(earnings),
        "period": f"{from_date} to {to_date}",
    }


def _fetch_ipo_calendar() -> dict:
    client = _get_finnhub_client()
    if client is None:
        raise ValueError("FINNHUB_API_KEY not configured")

    from_date = datetime.now().strftime("%Y-%m-%d")
    to_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

    raw = client.ipo_calendar(_from=from_date, to=to_date)
    ipos_raw = raw.get("ipoCalendar", []) if isinstance(raw, dict) else []

    ipos = []
    for ipo in ipos_raw:
        ipos.append({
            "date": ipo.get("date", ""),
            "name": ipo.get("name", ""),
            "symbol": ipo.get("symbol", ""),
            "exchange": ipo.get("exchange", ""),
            "price_range": f"{ipo.get('priceRangeLow', '?')}-{ipo.get('priceRangeHigh', '?')}",
            "shares": ipo.get("numberOfShares"),
            "total_shares_value": ipo.get("totalSharesValue"),
            "status": ipo.get("status", ""),
        })

    ipos.sort(key=lambda x: x["date"])

    return {
        "ipos": ipos,
        "total": len(ipos),
        "period": f"{from_date} to {to_date}",
    }


# --------------- Endpoints ---------------

@router.get("/economic/calendar")
async def get_economic_calendar(
    days_ahead: int = Query(7, description="Number of days to look ahead (1-30)", ge=1, le=30),
):
    """Get upcoming US economic events (CPI, FOMC, NFP, GDP, etc.) filtered by high/medium impact."""
    cache_key = f"econ_cal:{days_ahead}"
    cached = _get_cached(cache_key)
    if cached:
        return cached
    try:
        result = await asyncio.to_thread(_fetch_economic_calendar, days_ahead)
        _set_cache(cache_key, result, CACHE_TTL_CALENDAR)
        return result
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching economic calendar: {e}")


@router.get("/economic/earnings-calendar")
async def get_earnings_calendar(
    days_ahead: int = Query(14, description="Number of days to look ahead (1-60)", ge=1, le=60),
):
    """Get upcoming quarterly earnings reports."""
    cache_key = f"earnings_cal:{days_ahead}"
    cached = _get_cached(cache_key)
    if cached:
        return cached
    try:
        result = await asyncio.to_thread(_fetch_earnings_calendar, days_ahead)
        _set_cache(cache_key, result, CACHE_TTL_EARNINGS)
        return result
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching earnings calendar: {e}")


@router.get("/economic/ipo-calendar")
async def get_ipo_calendar():
    """Get upcoming IPOs for the next 30 days."""
    cache_key = "ipo_cal"
    cached = _get_cached(cache_key)
    if cached:
        return cached
    try:
        result = await asyncio.to_thread(_fetch_ipo_calendar)
        _set_cache(cache_key, result, CACHE_TTL_EARNINGS)
        return result
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching IPO calendar: {e}")
