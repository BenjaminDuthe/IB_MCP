"""Signal accuracy tracking — compare signals with subsequent price action."""

import logging
import time

import httpx

from scoring_engine.config import INFLUXDB_URL, INFLUXDB_DATABASE, INFLUXDB_USER, INFLUXDB_PASSWORD, MARKET_DATA_URL

logger = logging.getLogger(__name__)

_client = httpx.AsyncClient(timeout=15.0)


async def _query_influx(query: str) -> list[dict]:
    """Execute InfluxQL query and return results."""
    params = {"db": INFLUXDB_DATABASE, "q": query}
    if INFLUXDB_USER:
        params["u"] = INFLUXDB_USER
        params["p"] = INFLUXDB_PASSWORD
    try:
        resp = await _client.get(f"{INFLUXDB_URL}/query", params=params)
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", [{}])[0]
            series = results.get("series", [])
            if not series:
                return []
            cols = series[0]["columns"]
            return [dict(zip(cols, row)) for row in series[0]["values"]]
    except Exception as e:
        logger.error("InfluxDB query failed: %s", e)
    return []


async def get_recent_signals(limit: int = 50) -> list[dict]:
    """Get recent BUY signals from InfluxDB."""
    query = f"SELECT * FROM signals WHERE action='BUY' ORDER BY time DESC LIMIT {limit}"
    return await _query_influx(query)


async def get_price_at_time(ticker: str, timestamp: str) -> float | None:
    """Get the closest price to a given timestamp."""
    query = f"SELECT price FROM technicals WHERE ticker='{ticker}' AND time <= '{timestamp}' ORDER BY time DESC LIMIT 1"
    rows = await _query_influx(query)
    return rows[0]["price"] if rows else None


async def get_current_price(ticker: str) -> float | None:
    """Get latest price from market data service."""
    try:
        resp = await _client.get(f"{MARKET_DATA_URL}/stock/technicals/{ticker}")
        if resp.status_code == 200:
            return resp.json().get("price")
    except Exception:
        pass
    return None


async def compute_signal_accuracy(lookback_days: list[int] | None = None) -> dict:
    """Compute accuracy of recent signals.

    Returns {total_signals, profitable, win_rate, avg_return, signals: [...]}.
    """
    if lookback_days is None:
        lookback_days = [5, 10, 20]

    signals = await get_recent_signals(50)
    if not signals:
        return {"total_signals": 0, "profitable": 0, "win_rate": 0, "signals": []}

    results = []
    profitable = 0
    total_return = 0.0
    evaluated = 0

    for sig in signals:
        ticker = sig.get("ticker", "")
        signal_price = sig.get("price", 0)
        if not ticker or not signal_price:
            continue

        current = await get_current_price(ticker)
        if current is None:
            continue

        ret_pct = ((current - signal_price) / signal_price) * 100
        is_profitable = ret_pct > 0
        if is_profitable:
            profitable += 1
        total_return += ret_pct
        evaluated += 1

        results.append({
            "ticker": ticker,
            "signal_price": signal_price,
            "current_price": current,
            "return_pct": round(ret_pct, 2),
            "profitable": is_profitable,
            "time": sig.get("time"),
        })

    win_rate = (profitable / evaluated * 100) if evaluated > 0 else 0

    return {
        "total_signals": len(signals),
        "evaluated": evaluated,
        "profitable": profitable,
        "win_rate": round(win_rate, 1),
        "avg_return_pct": round(total_return / evaluated, 2) if evaluated > 0 else 0,
        "signals": results[:20],
    }
