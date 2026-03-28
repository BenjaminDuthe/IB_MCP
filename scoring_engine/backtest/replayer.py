"""Backtester: replay 10 years of InfluxDB data through the scoring engine.

For each day, compute the 5-filter score + fundamentals, then check
what happened 5/10/20/60 days later. Build a statistical model of
which score combinations actually predict profitable trades.

This replaces Claude's subjective conviction % with real data:
"Score 4/5 with fund>+0.5 → historically 78% profitable at +5d"
"""

import asyncio
import logging
import time
from collections import defaultdict

import httpx

from scoring_engine.config import INFLUXDB_URL, INFLUXDB_DATABASE, INFLUXDB_USER, INFLUXDB_PASSWORD

logger = logging.getLogger(__name__)

_client = httpx.AsyncClient(timeout=60.0)


async def _query(q: str) -> list[dict]:
    params = {"db": INFLUXDB_DATABASE, "q": q, "epoch": "s"}
    if INFLUXDB_USER:
        params["u"] = INFLUXDB_USER
        params["p"] = INFLUXDB_PASSWORD
    try:
        resp = await _client.get(f"{INFLUXDB_URL}/query", params=params)
        if resp.status_code == 200:
            data = resp.json()
            series = data.get("results", [{}])[0].get("series", [])
            if not series:
                return []
            cols = series[0]["columns"]
            return [dict(zip(cols, row)) for row in series[0]["values"]]
    except Exception as e:
        logger.error("InfluxDB query failed: %s", e)
    return []


async def get_ohlcv_history(ticker: str) -> list[dict]:
    """Get all daily OHLCV from backfilled data."""
    rows = await _query(
        f"SELECT time, close, open, high, low, volume FROM ohlcv "
        f"WHERE ticker='{ticker}' ORDER BY time ASC"
    )
    return rows


async def get_technicals_history(ticker: str) -> list[dict]:
    """Get all daily technicals from backfilled data."""
    rows = await _query(
        f"SELECT time, rsi_14, sma_20, sma_50, sma_200, atr_14, "
        f"macd_histogram, bollinger_upper, bollinger_lower, stochastic_k "
        f"FROM technicals_history WHERE ticker='{ticker}' ORDER BY time ASC"
    )
    return rows


def _compute_score_from_row(row: dict, close: float, close_5d_ago: float | None, params: dict) -> dict:
    """Compute 5-filter binary score from a single row of technicals."""
    sma_20 = row.get("sma_20")
    sma_200 = row.get("sma_200")
    rsi_14 = row.get("rsi_14")
    atr_14 = row.get("atr_14")

    # Filter 1: price > SMA20
    f1 = bool(sma_20 and close > sma_20)

    # Filter 2: 5-day trend > threshold
    trend_5d = ((close - close_5d_ago) / close_5d_ago * 100) if close_5d_ago and close_5d_ago > 0 else None
    f2 = bool(trend_5d is not None and trend_5d > params.get("t5d_threshold", 2.5))

    # Filter 3: RSI < threshold
    f3 = bool(rsi_14 is not None and rsi_14 < params.get("rsi_threshold", 55))

    # Filter 4: price > SMA200 (if required)
    if params.get("require_sma200", True):
        f4 = bool(sma_200 and close > sma_200)
    else:
        f4 = True

    # Filter 5: ATR relative < 2.5%
    atr_rel = (atr_14 / close * 100) if (atr_14 and close > 0) else None
    f5 = bool(atr_rel is not None and atr_rel < 2.5)

    score = sum([f1, f2, f3, f4, f5])
    return {"score": score, "filters": [f1, f2, f3, f4, f5], "trend_5d": trend_5d, "atr_rel": atr_rel}


async def backtest_ticker(ticker: str, params: dict, horizons: list[int] = None) -> dict:
    """Backtest one ticker over its full history.

    For each day with score >= 3, check if buying was profitable
    at 5/10/20/60 days later.

    Returns stats per score level (3, 4, 5).
    """
    if horizons is None:
        horizons = [5, 10, 20, 60]

    ohlcv = await get_ohlcv_history(ticker)
    technicals = await get_technicals_history(ticker)

    if not ohlcv or not technicals:
        return {"ticker": ticker, "error": "no_data", "bars": 0}

    # Index technicals by timestamp
    tech_by_time = {r["time"]: r for r in technicals}

    # Build close price index
    closes = [(r["time"], r["close"]) for r in ohlcv if r.get("close")]
    close_by_idx = {i: (t, c) for i, (t, c) in enumerate(closes)}

    results_by_score = defaultdict(lambda: {h: {"total": 0, "profitable": 0, "returns": []} for h in horizons})

    for i, (ts, close) in enumerate(closes):
        if close is None or close <= 0:
            continue

        tech = tech_by_time.get(ts)
        if not tech:
            continue

        # 5-day ago close
        close_5d_ago = close_by_idx[i - 5][1] if (i - 5) in close_by_idx else None

        score_data = _compute_score_from_row(tech, close, close_5d_ago, params)
        score = score_data["score"]

        if score < 3:
            continue

        # Check future returns at each horizon
        for h in horizons:
            future_idx = i + h
            if future_idx not in close_by_idx:
                continue
            future_close = close_by_idx[future_idx][1]
            if future_close is None:
                continue

            ret = (future_close - close) / close * 100
            bucket = results_by_score[score][h]
            bucket["total"] += 1
            if ret > 0:
                bucket["profitable"] += 1
            bucket["returns"].append(ret)

    # Compute stats
    stats = {}
    for score_level in sorted(results_by_score.keys()):
        stats[f"score_{score_level}"] = {}
        for h in horizons:
            bucket = results_by_score[score_level][h]
            total = bucket["total"]
            profitable = bucket["profitable"]
            returns = bucket["returns"]
            if total > 0:
                win_rate = profitable / total * 100
                avg_ret = sum(returns) / len(returns)
                median_ret = sorted(returns)[len(returns) // 2]
                max_loss = min(returns) if returns else 0
                max_gain = max(returns) if returns else 0
            else:
                win_rate = avg_ret = median_ret = max_loss = max_gain = 0

            stats[f"score_{score_level}"][f"{h}d"] = {
                "total_signals": total,
                "profitable": profitable,
                "win_rate": round(win_rate, 1),
                "avg_return": round(avg_ret, 2),
                "median_return": round(median_ret, 2),
                "max_gain": round(max_gain, 2),
                "max_loss": round(max_loss, 2),
            }

    return {
        "ticker": ticker,
        "bars": len(closes),
        "stats": stats,
    }


async def backtest_all(tickers_params: dict[str, dict], horizons: list[int] = None) -> dict:
    """Backtest all tickers and aggregate results.

    Returns global win rates per score level per horizon.
    """
    start = time.time()
    results = {}
    global_stats = defaultdict(lambda: defaultdict(lambda: {"total": 0, "profitable": 0, "returns": []}))

    for ticker, params in tickers_params.items():
        r = await backtest_ticker(ticker, params, horizons)
        results[ticker] = r

        # Aggregate
        for score_key, horizons_data in r.get("stats", {}).items():
            for h_key, h_data in horizons_data.items():
                g = global_stats[score_key][h_key]
                g["total"] += h_data["total_signals"]
                g["profitable"] += h_data["profitable"]
                g["returns"].extend([h_data["avg_return"]] * h_data["total_signals"])

    # Compute global averages
    global_summary = {}
    for score_key in sorted(global_stats.keys()):
        global_summary[score_key] = {}
        for h_key, g in global_stats[score_key].items():
            total = g["total"]
            if total > 0:
                win_rate = g["profitable"] / total * 100
                avg_ret = sum(g["returns"]) / len(g["returns"]) if g["returns"] else 0
            else:
                win_rate = avg_ret = 0
            global_summary[score_key][h_key] = {
                "total_signals": total,
                "win_rate": round(win_rate, 1),
                "avg_return": round(avg_ret, 2),
            }

    duration = time.time() - start
    return {
        "duration_seconds": round(duration, 1),
        "tickers_tested": len(results),
        "global_summary": global_summary,
        "per_ticker": results,
    }
