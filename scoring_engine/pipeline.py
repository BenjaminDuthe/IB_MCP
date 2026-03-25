"""Pipeline: collect → analysts (Ollama) → OpenClaw (Claude) decides → alert."""

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
    RISK_SIZING_ENABLED,
)
from scoring_engine.scorer import compute_score
from scoring_engine.influx_writer import (
    write_technicals,
    write_sentiment,
    write_scoring,
    write_signal,
    write_pipeline_status,
    write_analyst_reports,
)
from scoring_engine.alerter import alert_signal, alert_scan_summary, alert_daily_summary

logger = logging.getLogger(__name__)

_client = httpx.AsyncClient(timeout=30.0)

# Lazy-init agents
_agents_initialized = False
_init_lock = asyncio.Lock()
_technical_agent = None
_fundamental_agent = None
_macro_agent = None
_sentiment_agent = None


async def _init_agents():
    global _agents_initialized, _technical_agent, _fundamental_agent, _macro_agent, _sentiment_agent
    if _agents_initialized:
        return
    async with _init_lock:
        if _agents_initialized:
            return
        from scoring_engine.agents import TechnicalAnalyst, FundamentalAnalyst, MacroAnalyst, SentimentAnalyst
        _technical_agent = TechnicalAnalyst()
        _fundamental_agent = FundamentalAnalyst()
        _macro_agent = MacroAnalyst()
        _sentiment_agent = SentimentAnalyst()
        _agents_initialized = True


# --- Data fetchers ---

async def _fetch(url: str, label: str) -> dict | None:
    try:
        resp = await _client.get(url)
        if resp.status_code == 200:
            return resp.json()
        logger.warning("%s: HTTP %d", label, resp.status_code)
    except Exception as e:
        logger.error("%s fetch failed: %s", label, e)
    return None


async def _fetch_macro_overview() -> dict:
    macro, sectors = await asyncio.gather(
        _fetch(f"{MARKET_DATA_URL}/stock/market-overview", "macro"),
        _fetch(f"{MARKET_DATA_URL}/stock/sector-performance", "sectors"),
    )
    return {"macro": macro or {}, "sectors": sectors or {}}


# --- Core pipeline ---

async def scan_ticker(ticker: str, macro_context: dict | None = None) -> dict:
    """Analyse one ticker: data + 4 analysts. No verdict — OpenClaw decides later."""
    result = {"ticker": ticker, "error": None}

    # Fetch all data in parallel
    await _init_agents()
    technicals, sentiment, fundamentals, analyst_data = await asyncio.gather(
        _fetch(f"{MARKET_DATA_URL}/stock/technicals/{ticker}", f"technicals/{ticker}"),
        _fetch(f"{SENTIMENT_URL}/sentiment/combined/{ticker}", f"sentiment/{ticker}"),
        _fetch(f"{MARKET_DATA_URL}/stock/fundamentals/{ticker}", f"fundamentals/{ticker}"),
        _fetch(f"{MARKET_DATA_URL}/stock/analyst/{ticker}", f"analyst/{ticker}"),
    )

    if not technicals:
        result["error"] = "technicals_unavailable"
        return result

    # Binary score (5 filters)
    score_data = compute_score(ticker, technicals)
    result["score"] = score_data

    # 4 analyst agents (factual reports, no verdict)
    reports = await asyncio.gather(
        _technical_agent.analyze(ticker, {"technicals": technicals, "score_data": score_data}),
        _fundamental_agent.analyze(ticker, {"fundamentals": fundamentals, "analyst": analyst_data}),
        _macro_agent.analyze(ticker, macro_context or {}),
        _sentiment_agent.analyze(ticker, {"sentiment": sentiment}),
    )
    result["analyst_reports"] = [r.to_dict() for r in reports]

    # Placeholder LLM (will be overridden by OpenClaw in scan_tickers)
    result["llm"] = {"verdict": "HOLD", "confidence": 0, "summary": "En attente de décision OpenClaw"}

    # Write to InfluxDB
    await write_technicals(ticker, score_data["market"], technicals)
    if sentiment and sentiment.get("unified_score") is not None:
        await write_sentiment(ticker, "combined", sentiment["unified_score"], sentiment.get("unified_label", "neutral"))
    await write_analyst_reports(ticker, reports)

    return result


async def scan_tickers(tickers: list[str]) -> dict:
    """Scan all tickers then send to OpenClaw for portfolio-level decisions."""
    start = time.time()
    results = []
    errors = 0
    signals = 0

    # Shared macro context (1 fetch for all tickers)
    macro_context = await _fetch_macro_overview()

    # Reset risk cycle
    if RISK_SIZING_ENABLED:
        from scoring_engine.risk.portfolio_risk import reset_cycle
        await reset_cycle()

    # Scan all tickers (Ollama factual reports)
    for ticker in tickers:
        r = await scan_ticker(ticker, macro_context=macro_context)
        results.append(r)
        if r.get("error"):
            errors += 1

    # --- OpenClaw (Claude) decides for ALL tickers at once ---
    openclaw_verdicts = None
    valid_results = [r for r in results if not r.get("error")]
    if valid_results:
        from scoring_engine.openclaw_decision import get_openclaw_verdicts
        openclaw_verdicts = await get_openclaw_verdicts(valid_results)
        if openclaw_verdicts:
            rankings = {v["ticker"]: v for v in openclaw_verdicts.get("rankings", [])}
            for r in results:
                ticker = r.get("ticker", r.get("score", {}).get("ticker", ""))
                v = rankings.get(ticker)
                if v:
                    r["llm"] = {
                        "verdict": v.get("verdict", "HOLD"),
                        "confidence": v.get("conviction", 0),
                        "summary": v.get("reason", ""),
                    }
                    r["openclaw_risk"] = v.get("risk", "")
                    r["openclaw_rank"] = v.get("rank", 99)
                    r["bull_case"] = v.get("bull_case", "")
                    r["bear_case"] = v.get("bear_case", "")
                    r["openclaw_target_price"] = v.get("target_price")
                    r["openclaw_horizon"] = v.get("horizon", "")

    # Risk gate + signal detection
    for r in results:
        s = r.get("score", {})
        l = r.get("llm", {})
        if l.get("verdict") == "BUY" and l.get("confidence", 0) >= 60:
            if RISK_SIZING_ENABLED:
                from scoring_engine.risk import enhanced_risk_check
                risk_result = await enhanced_risk_check(r.get("ticker", ""), s, l)
                r["risk"] = risk_result
                if not risk_result.get("approved", True):
                    l["verdict"] = "HOLD"
                    l["summary"] += f" [Risk: {risk_result.get('reason', '')}]"
            if l.get("verdict") == "BUY":
                signals += 1
                r["signal_sent"] = True
                await write_signal(r["ticker"], "BUY", l["confidence"], s.get("price", 0), s.get("score", 0), l["summary"])
                await write_scoring(r["ticker"], s.get("market", ""), s, l)

    duration = time.time() - start
    await write_pipeline_status("scoring_v2", duration, len(tickers), signals, errors)

    return {
        "tickers_scanned": len(tickers),
        "signals_generated": signals,
        "openclaw_verdicts": openclaw_verdicts,
        "errors": errors,
        "duration_seconds": round(duration, 1),
        "results": results,
    }


async def scan_market(market: str) -> dict:
    """Scan all tickers for a market (legacy compat)."""
    tickers = [t for t, cfg in WATCHLIST.items() if cfg["market"] == market]
    logger.info("Scanning %s market: %s", market, tickers)
    result = await scan_tickers(tickers)
    await alert_scan_summary(market, result["results"], result.get("openclaw_verdicts"))
    return result


async def scan_exchange(exchange: str) -> dict:
    """Scan all tickers for a specific exchange (Paris, Frankfurt, etc.)."""
    from scoring_engine.config import EXCHANGE_GROUPS
    tickers = EXCHANGE_GROUPS.get(exchange, [])
    if not tickers:
        logger.warning("No tickers for exchange %s", exchange)
        return {"error": f"Unknown exchange: {exchange}"}
    logger.info("Scanning %s exchange: %d tickers", exchange, len(tickers))
    result = await scan_tickers(tickers)
    await alert_scan_summary(exchange, result["results"], result.get("openclaw_verdicts"))
    return result


async def get_top_signals(limit: int = 3) -> list[dict]:
    all_tickers = list(WATCHLIST.keys())
    scan = await scan_tickers(all_tickers)
    scored = [r for r in scan["results"] if r.get("score") and not r.get("error")]
    scored.sort(key=lambda r: r.get("openclaw_rank", 99))
    return scored[:limit]


async def generate_daily_summary() -> str:
    all_tickers = list(WATCHLIST.keys())
    scan = await scan_tickers(all_tickers)

    lines = []
    sorted_results = sorted(scan["results"], key=lambda r: r.get("openclaw_rank", 99))
    for r in sorted_results:
        if r.get("error"):
            lines.append(f"❌ {r['ticker']}: {r['error']}")
            continue
        s = r["score"]
        l = r.get("llm", {})
        emoji = "🟢" if l.get("verdict") == "BUY" else ("🔴" if l.get("verdict") == "SELL" else "🟡")
        line = f"{emoji} {s['ticker']}: {s['score']}/5 — {l.get('verdict', '?')} ({l.get('confidence', 0)}%) ${s['price']:.2f}"
        if r.get("openclaw_risk"):
            line += f" ⚠️{r['openclaw_risk'][:50]}"
        lines.append(line)

    summary = "\n".join(lines)
    summary += f"\n\n📈 {scan['tickers_scanned']} tickers | {scan['signals_generated']} signaux | {scan['duration_seconds']}s"

    await alert_daily_summary(summary)
    return summary
