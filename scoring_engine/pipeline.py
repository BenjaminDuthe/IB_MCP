"""Main orchestration: collect → analysts → debate → risk → store → alert."""

import asyncio
import logging
import time

import httpx

from scoring_engine.config import (
    MARKET_DATA_URL,
    SENTIMENT_URL,
    WATCHLIST,
    SIGNAL_SCORE_THRESHOLD,
    AGENT_LAYERS_ENABLED,
    DEBATE_ENABLED,
    RISK_SIZING_ENABLED,
)
from scoring_engine.scorer import compute_score
from scoring_engine.sentiment_llm import synthesize_verdict
from scoring_engine.influx_writer import (
    write_technicals,
    write_sentiment,
    write_scoring,
    write_signal,
    write_pipeline_status,
    write_analyst_reports,
    write_debate,
)
from scoring_engine.alerter import alert_signal, alert_scan_summary, alert_daily_summary

logger = logging.getLogger(__name__)

_client = httpx.AsyncClient(timeout=30.0)

# Lazy-init agents (only when AGENT_LAYERS_ENABLED)
_agents_initialized = False
_technical_agent = None
_fundamental_agent = None
_macro_agent = None
_sentiment_agent = None


_init_lock = asyncio.Lock()


async def _init_agents():
    global _agents_initialized, _technical_agent, _fundamental_agent, _macro_agent, _sentiment_agent
    if _agents_initialized:
        return
    async with _init_lock:
        if _agents_initialized:  # double-check after acquiring lock
            return
        from scoring_engine.agents import TechnicalAnalyst, FundamentalAnalyst, MacroAnalyst, SentimentAnalyst
        _technical_agent = TechnicalAnalyst()
        _fundamental_agent = FundamentalAnalyst()
        _macro_agent = MacroAnalyst()
        _sentiment_agent = SentimentAnalyst()
        _agents_initialized = True


# --- Data fetchers ---

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


async def _fetch_fundamentals(ticker: str) -> dict | None:
    try:
        resp = await _client.get(f"{MARKET_DATA_URL}/stock/fundamentals/{ticker}")
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.error("Fundamentals fetch failed for %s: %s", ticker, e)
    return None


async def _fetch_analyst(ticker: str) -> dict | None:
    try:
        resp = await _client.get(f"{MARKET_DATA_URL}/stock/analyst/{ticker}")
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.error("Analyst fetch failed for %s: %s", ticker, e)
    return None


async def _fetch_macro_overview() -> dict:
    """Fetch macro data ONCE per scan cycle (shared across tickers)."""
    macro = {}
    sectors = {}
    try:
        resp = await _client.get(f"{MARKET_DATA_URL}/stock/market-overview")
        if resp.status_code == 200:
            macro = resp.json()
    except Exception as e:
        logger.error("Macro overview fetch failed: %s", e)
    try:
        resp = await _client.get(f"{MARKET_DATA_URL}/stock/sector-performance")
        if resp.status_code == 200:
            sectors = resp.json()
    except Exception as e:
        logger.error("Sector performance fetch failed: %s", e)
    return {"macro": macro, "sectors": sectors}


# --- Core pipeline ---

async def scan_ticker(ticker: str, macro_context: dict | None = None) -> dict:
    """Full analysis pipeline for a single ticker."""
    result = {"ticker": ticker, "error": None}

    # --- PHASE 1: Fetch data ---
    if AGENT_LAYERS_ENABLED:
        await _init_agents()
        technicals, sentiment, fundamentals, analyst_data = await asyncio.gather(
            _fetch_technicals(ticker),
            _fetch_sentiment(ticker),
            _fetch_fundamentals(ticker),
            _fetch_analyst(ticker),
        )
    else:
        technicals = await _fetch_technicals(ticker)
        sentiment = await _fetch_sentiment(ticker)
        fundamentals = None
        analyst_data = None

    if not technicals:
        result["error"] = "technicals_unavailable"
        return result

    # --- PHASE 2: Compute base score (always) ---
    score_data = compute_score(ticker, technicals)
    result["score"] = score_data

    # --- PHASE 3: Run analyst agents (if enabled) ---
    if AGENT_LAYERS_ENABLED:
        reports = await asyncio.gather(
            _technical_agent.analyze(ticker, {"technicals": technicals, "score_data": score_data}),
            _fundamental_agent.analyze(ticker, {"fundamentals": fundamentals, "analyst": analyst_data}),
            _macro_agent.analyze(ticker, macro_context or {}),
            _sentiment_agent.analyze(ticker, {"sentiment": sentiment}),
        )
        result["analyst_reports"] = [r.to_dict() for r in reports]
        await write_analyst_reports(ticker, reports)

        # --- PHASE 4: Debate (if enabled) ---
        if DEBATE_ENABLED:
            from scoring_engine.debate import run_debate
            debate_result = await run_debate(ticker, reports)
            result["debate"] = debate_result
            llm = {
                "verdict": debate_result["verdict"],
                "confidence": debate_result["confidence"],
                "summary": debate_result["summary"],
            }
        else:
            llm = await synthesize_verdict(ticker, score_data["score"], technicals, sentiment)
    else:
        # LEGACY PATH: unchanged v1 behavior
        llm = await synthesize_verdict(ticker, score_data["score"], technicals, sentiment)

    result["llm"] = llm

    # --- PHASE 5: Risk gate (if enabled) ---
    if RISK_SIZING_ENABLED and llm["verdict"] == "BUY":
        from scoring_engine.risk import enhanced_risk_check
        risk_result = await enhanced_risk_check(ticker, score_data, llm)
        result["risk"] = risk_result
        if not risk_result.get("approved", True):
            llm["verdict"] = "HOLD"
            llm["summary"] += f" [Risk: {risk_result.get('reason', '?')}]"

    # --- PHASE 6: Write to InfluxDB ---
    await write_technicals(ticker, score_data["market"], technicals)
    if sentiment and "unified_score" in sentiment:
        await write_sentiment(
            ticker, "combined",
            sentiment["unified_score"],
            sentiment.get("unified_label", "neutral"),
        )
    await write_scoring(ticker, score_data["market"], score_data, llm)

    if AGENT_LAYERS_ENABLED and DEBATE_ENABLED and result.get("debate"):
        await write_debate(ticker, result["debate"])

    # --- PHASE 7: Signal + alert ---
    if score_data["score"] >= SIGNAL_SCORE_THRESHOLD and llm["verdict"] == "BUY":
        await write_signal(
            ticker, "BUY", llm["confidence"],
            score_data["price"], score_data["score"], llm["summary"],
        )
        await alert_signal(
            ticker, score_data["score"], score_data["price"],
            llm["verdict"], llm["confidence"], llm["summary"],
            filters=score_data.get("filters"),
            values=score_data.get("values"),
            debate=result.get("debate"),
            analyst_reports=result.get("analyst_reports"),
            risk=result.get("risk"),
        )
        result["signal_sent"] = True

    return result


async def scan_tickers(tickers: list[str]) -> dict:
    """Scan a list of tickers and return aggregated results."""
    start = time.time()
    results = []
    errors = 0
    signals = 0

    # Fetch shared macro context once for all tickers
    macro_context = None
    if AGENT_LAYERS_ENABLED:
        macro_context = await _fetch_macro_overview()

    # Reset per-cycle risk state
    if RISK_SIZING_ENABLED:
        from scoring_engine.risk.portfolio_risk import reset_cycle
        await reset_cycle()

    for ticker in tickers:
        r = await scan_ticker(ticker, macro_context=macro_context)
        results.append(r)
        if r.get("error"):
            errors += 1
        if r.get("signal_sent"):
            signals += 1

    duration = time.time() - start
    pipeline_name = "scoring_v2" if AGENT_LAYERS_ENABLED else "scoring"
    await write_pipeline_status(pipeline_name, duration, len(tickers), signals, errors)

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
    result = await scan_tickers(tickers)
    await alert_scan_summary(market, result["results"])
    return result


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
        line = f"{emoji} {s['ticker']}: {s['score']}/5 — {llm.get('verdict', '?')} ({llm.get('confidence', 0)}%) ${s['price']:.2f}"
        # Add analyst scores if available
        if r.get("analyst_reports"):
            scores = {a["agent_name"]: a["score"] for a in r["analyst_reports"]}
            line += f" | F:{scores.get('fundamental', 0):+.1f} M:{scores.get('macro', 0):+.1f}"
        lines.append(line)

    summary = "\n".join(lines)
    summary += f"\n\n📈 Scannes: {scan['tickers_scanned']} | Signaux: {scan['signals_generated']} | Duree: {scan['duration_seconds']}s"
    if AGENT_LAYERS_ENABLED:
        summary += " | Mode: multi-agent"

    await alert_daily_summary(summary)
    return summary
