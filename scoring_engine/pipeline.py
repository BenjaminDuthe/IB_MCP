"""Main orchestration: collect → score → store → alert."""

import logging
import time

import httpx

from scoring_engine.config import (
    MARKET_DATA_URL,
    SENTIMENT_URL,
    WATCHLIST,
    SIGNAL_SCORE_THRESHOLD,
)
from scoring_engine.scorer import compute_score
from scoring_engine.sentiment_llm import synthesize_verdict
from scoring_engine.influx_writer import (
    write_technicals,
    write_sentiment,
    write_scoring,
    write_signal,
    write_pipeline_status,
)
from scoring_engine.alerter import alert_signal, alert_daily_summary

logger = logging.getLogger(__name__)

_client = httpx.AsyncClient(timeout=30.0)


async def _fetch_technicals(ticker: str) -> dict | None:
    try:
        resp = await _client.get(f"{MARKET_DATA_URL}/stock/technicals/{ticker}")
        if resp.status_code == 200:
            return resp.json()
        logger.warning("Technicals %s: HTTP %d", ticker, resp.status_code)
    except Exception as e:
        logger.error("Technicals fetch failed for %s: %s", ticker, e)
    return None


async def _fetch_sentiment(ticker: str) -> dict | None:
    try:
        resp = await _client.get(f"{SENTIMENT_URL}/sentiment/combined/{ticker}")
        if resp.status_code == 200:
            return resp.json()
        logger.warning("Sentiment %s: HTTP %d", ticker, resp.status_code)
    except Exception as e:
        logger.error("Sentiment fetch failed for %s: %s", ticker, e)
    return None


async def scan_ticker(ticker: str) -> dict:
    """Full analysis pipeline for a single ticker."""
    result = {"ticker": ticker, "error": None}

    # 1. Fetch technicals
    technicals = await _fetch_technicals(ticker)
    if not technicals:
        result["error"] = "technicals_unavailable"
        return result

    # 2. Compute binary score
    score_data = compute_score(ticker, technicals)
    result["score"] = score_data

    # 3. Write technicals to InfluxDB
    await write_technicals(ticker, score_data["market"], technicals)

    # 4. Fetch sentiment (non-blocking, optional)
    sentiment = await _fetch_sentiment(ticker)
    if sentiment and "unified_score" in sentiment:
        await write_sentiment(
            ticker,
            "combined",
            sentiment["unified_score"],
            sentiment.get("unified_label", "neutral"),
        )

    # 5. LLM synthesis
    llm = await synthesize_verdict(ticker, score_data["score"], technicals, sentiment)
    result["llm"] = llm

    # 6. Write scoring to InfluxDB
    await write_scoring(ticker, score_data["market"], score_data, llm)

    # 7. Alert if score >= threshold and verdict is BUY
    if score_data["score"] >= SIGNAL_SCORE_THRESHOLD and llm["verdict"] == "BUY":
        await write_signal(
            ticker, "BUY", llm["confidence"], score_data["price"], score_data["score"], llm["summary"]
        )
        await alert_signal(
            ticker, score_data["score"], score_data["price"],
            llm["verdict"], llm["confidence"], llm["summary"],
        )
        result["signal_sent"] = True

    return result


async def scan_tickers(tickers: list[str]) -> dict:
    """Scan a list of tickers and return aggregated results."""
    start = time.time()
    results = []
    errors = 0
    signals = 0

    for ticker in tickers:
        r = await scan_ticker(ticker)
        results.append(r)
        if r.get("error"):
            errors += 1
        if r.get("signal_sent"):
            signals += 1

    duration = time.time() - start
    await write_pipeline_status("scoring", duration, len(tickers), signals, errors)

    return {
        "tickers_scanned": len(tickers),
        "signals_generated": signals,
        "errors": errors,
        "duration_seconds": round(duration, 1),
        "results": results,
    }


async def scan_market(market: str) -> dict:
    """Scan all tickers for a given market (US or FR)."""
    tickers = [t for t, cfg in WATCHLIST.items() if cfg["market"] == market]
    logger.info("Scanning %s market: %s", market, tickers)
    return await scan_tickers(tickers)


async def get_top_signals(limit: int = 3) -> list[dict]:
    """Scan all tickers and return top signals by score."""
    all_tickers = list(WATCHLIST.keys())
    scan = await scan_tickers(all_tickers)
    scored = [
        r for r in scan["results"]
        if r.get("score") and not r.get("error")
    ]
    scored.sort(key=lambda r: r["score"]["score"], reverse=True)
    return scored[:limit]


async def generate_daily_summary() -> str:
    """Generate end-of-day summary text."""
    all_tickers = list(WATCHLIST.keys())
    scan = await scan_tickers(all_tickers)

    lines = []
    for r in scan["results"]:
        if r.get("error"):
            lines.append(f"❌ {r['ticker']}: {r['error']}")
            continue
        s = r["score"]
        llm = r.get("llm", {})
        emoji = "🟢" if s["score"] >= 4 else ("🟡" if s["score"] >= 3 else "⚪")
        lines.append(
            f"{emoji} {s['ticker']}: {s['score']}/5 — "
            f"{llm.get('verdict', '?')} ({llm.get('confidence', 0)}%) "
            f"${s['price']:.2f}"
        )

    summary = "\n".join(lines)
    summary += f"\n\n📈 Scannes: {scan['tickers_scanned']} | Signaux: {scan['signals_generated']} | Duree: {scan['duration_seconds']}s"

    await alert_daily_summary(summary)
    return summary
