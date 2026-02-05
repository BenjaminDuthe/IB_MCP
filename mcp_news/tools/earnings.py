import os
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/news", tags=["Earnings Calendar"])


def _get_finnhub_client():
    import finnhub

    api_key = os.environ.get("FINNHUB_API_KEY")
    if not api_key:
        return None
    return finnhub.Client(api_key=api_key)


@router.get("/earnings")
async def get_earnings_calendar(
    days: int = Query(7, ge=1, le=30, description="Number of days ahead to look"),
):
    """Get upcoming earnings calendar from Finnhub."""
    client = _get_finnhub_client()
    if client is None:
        raise HTTPException(status_code=503, detail="Finnhub API not configured. Set FINNHUB_API_KEY.")

    try:
        today = datetime.now()
        from_date = today.strftime("%Y-%m-%d")
        to_date = (today + timedelta(days=days)).strftime("%Y-%m-%d")

        calendar = client.earnings_calendar(_from=from_date, to=to_date, symbol="", international=False)

        earnings = []
        for item in calendar.get("earningsCalendar", [])[:50]:
            earnings.append({
                "symbol": item.get("symbol"),
                "date": item.get("date"),
                "hour": item.get("hour"),
                "eps_estimate": item.get("epsEstimate"),
                "eps_actual": item.get("epsActual"),
                "revenue_estimate": item.get("revenueEstimate"),
                "revenue_actual": item.get("revenueActual"),
                "quarter": item.get("quarter"),
                "year": item.get("year"),
            })

        return {
            "period": f"{from_date} to {to_date}",
            "earnings_count": len(earnings),
            "earnings": earnings,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
