"""Grok X Search — real-time X/Twitter sentiment via xAI API.

Two modes:
- GET /grok-x/{ticker} — simple search (legacy, backward compat)
- POST /grok-x-contextual/{ticker} — full briefing confrontation (used by pipeline)

Activated ONLY when Fear & Greed < 30 (Extreme Fear).
US tickers only (48) — EU tickers have no meaningful $cashtag volume.
"""

import asyncio
import json
import logging
import os
from datetime import datetime

from fastapi import APIRouter, Body

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sentiment", tags=["Grok X Sentiment"])

GROK_API_KEY = os.environ.get("GROK_API_KEY", "")
GROK_BASE_URL = "https://api.x.ai/v1"
GROK_MODEL = "grok-3-mini"

# Cache: ticker → (result, timestamp)
_cache: dict[str, tuple[dict, float]] = {}
CACHE_TTL = 3600  # 1 hour

_EU_SUFFIXES = (".PA", ".DE", ".AS", ".SW", ".L")

SYSTEM_PROMPT_CONTEXTUAL = (
    "Tu es un analyste sentiment contrarian specialise dans les reseaux sociaux financiers. "
    "Tu recois un briefing complet d'un autre analyste (donnees techniques, fondamentales, macro, sentiment multi-sources). "
    "Ta mission : confronter ce briefing avec le sentiment REEL sur X/Twitter. "
    "Cherche les $cashtags, les avis de traders influents, les reactions aux news. "
    "Identifie les DIVERGENCES entre notre analyse et ce que dit X. "
    "Si tout le monde panique mais nos indicateurs disent achat, c'est un signal contrarian fort. "
    "Si X confirme notre analyse, dis-le aussi. "
    "Reponds UNIQUEMENT en JSON valide, rien d'autre : "
    '{"score": <float -1 a +1>, "divergence": "<confirme|neutre|contredit>", '
    '"divergence_detail": "<explication courte>", '
    '"volume": "<low|medium|high>", "bull_count": <int>, "bear_count": <int>, '
    '"key_themes": [<max 5 strings>], "signal_quality": "<noise|mixed|strong>", '
    '"contrarian_signal": <bool>}'
)


def _build_briefing_prompt(ticker: str, briefing: dict) -> str:
    """Build the contextual user prompt from all available data."""
    price = briefing.get("price", "?")
    regime = briefing.get("regime", "?")
    vix = briefing.get("vix", "?")
    fg = briefing.get("fear_greed_raw", "?")
    tech_score = briefing.get("technical_score", "?")
    rsi = briefing.get("rsi_14", "?")
    trend_5d = briefing.get("trend_5d", "?")
    macd = briefing.get("macd_signal", "?")
    fund_score = briefing.get("fundamental_score", "?")
    pe = briefing.get("forward_pe", "?")
    revenue_growth = briefing.get("revenue_growth", "?")
    target = briefing.get("analyst_target", "?")
    sentiment_score = briefing.get("sentiment_score", "?")
    sources_used = briefing.get("sources_used", [])
    active = briefing.get("active_signals", [])
    watch = briefing.get("watch_signals", [])

    active_str = ", ".join(s.get("name", s) if isinstance(s, dict) else str(s) for s in active) if active else "aucun"
    watch_str = ", ".join(s.get("name", s) if isinstance(s, dict) else str(s) for s in watch) if watch else "aucun"
    sources_str = ", ".join(sources_used) if sources_used else "aucune"

    return (
        f"BRIEFING ANALYSTE pour ${ticker} :\n"
        f"- Prix: ${price} | Regime: {regime} (VIX {vix}, Fear&Greed {fg}/100)\n"
        f"- Score technique: {tech_score}/5 | RSI: {rsi} | MACD: {macd} | Tendance 5j: {trend_5d}%\n"
        f"- Score fondamental: {fund_score} | P/E: {pe} | Croissance CA: {revenue_growth} | Target: ${target}\n"
        f"- Sentiment actuel (hors X): {sentiment_score} ({sources_str})\n"
        f"- Signaux V4 actifs: {active_str} | Watch: {watch_str}\n\n"
        f"Confronte ce briefing avec ce que tu vois sur X pour ${ticker}. "
        f"Y a-t-il une divergence entre notre analyse et le sentiment des traders sur X ?"
    )


def _parse_grok_response(raw: str) -> dict:
    """Parse Grok JSON response, handling markdown code blocks."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    return json.loads(text)


async def _call_grok(messages: list[dict]) -> str:
    """Call Grok API and return raw response text."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(base_url=GROK_BASE_URL, api_key=GROK_API_KEY)
    response = await asyncio.wait_for(
        client.chat.completions.create(model=GROK_MODEL, messages=messages),
        timeout=30.0,
    )
    return response.choices[0].message.content.strip()


@router.post("/grok-x-contextual/{ticker}")
async def get_grok_x_contextual(ticker: str, briefing: dict = Body(...)):
    """Contextual Grok X analysis — confronts our full briefing with X/Twitter sentiment."""
    ticker = ticker.upper()

    if any(ticker.endswith(s) for s in _EU_SUFFIXES):
        return {"ticker": ticker, "skipped": "not_us_ticker", "sentiment_score": None}

    if not GROK_API_KEY:
        return {"ticker": ticker, "skipped": "no_api_key", "sentiment_score": None}

    now = datetime.utcnow().timestamp()
    cache_key = f"ctx_{ticker}"
    if cache_key in _cache:
        cached, ts = _cache[cache_key]
        if now - ts < CACHE_TTL:
            return cached

    try:
        raw = await _call_grok([
            {"role": "system", "content": SYSTEM_PROMPT_CONTEXTUAL},
            {"role": "user", "content": _build_briefing_prompt(ticker, briefing)},
        ])
        data = _parse_grok_response(raw)

        score = max(-1.0, min(1.0, float(data.get("score", 0))))

        result = {
            "ticker": ticker,
            "sentiment_score": round(score, 3),
            "divergence": data.get("divergence", "neutre"),
            "divergence_detail": data.get("divergence_detail", ""),
            "volume": data.get("volume", "unknown"),
            "bull_count": data.get("bull_count", 0),
            "bear_count": data.get("bear_count", 0),
            "key_themes": data.get("key_themes", [])[:5],
            "signal_quality": data.get("signal_quality", "unknown"),
            "contrarian_signal": data.get("contrarian_signal", False),
            "model": GROK_MODEL,
        }
        _cache[cache_key] = (result, now)
        return result

    except json.JSONDecodeError:
        logger.warning("Grok contextual non-JSON for %s: %s", ticker, raw[:200])
        return {"ticker": ticker, "sentiment_score": None, "error": "json_parse_error"}
    except asyncio.TimeoutError:
        logger.warning("Grok contextual timeout for %s", ticker)
        return {"ticker": ticker, "sentiment_score": None, "error": "timeout"}
    except Exception as e:
        logger.error("Grok contextual failed for %s: %s", ticker, e)
        return {"ticker": ticker, "sentiment_score": None, "error": str(e)}


@router.get("/grok-x/{ticker}")
async def get_grok_x_sentiment(ticker: str):
    """Legacy simple Grok X search (no briefing context)."""
    ticker = ticker.upper()

    if any(ticker.endswith(s) for s in _EU_SUFFIXES):
        return {"ticker": ticker, "skipped": "not_us_ticker", "sentiment_score": None}

    if not GROK_API_KEY:
        return {"ticker": ticker, "skipped": "no_api_key", "sentiment_score": None}

    now = datetime.utcnow().timestamp()
    if ticker in _cache:
        cached, ts = _cache[ticker]
        if now - ts < CACHE_TTL:
            return cached

    try:
        raw = await _call_grok([
            {"role": "system", "content": SYSTEM_PROMPT_CONTEXTUAL},
            {"role": "user", "content": (
                f"Analyse le sentiment actuel sur X pour ${ticker}. "
                f"Le marche est en mode peur elevee (Fear & Greed < 30). "
                f"Que disent les traders ? Signaux contrarians ou panique ?"
            )},
        ])
        data = _parse_grok_response(raw)
        score = max(-1.0, min(1.0, float(data.get("score", 0))))

        result = {
            "ticker": ticker,
            "sentiment_score": round(score, 3),
            "divergence": data.get("divergence", "neutre"),
            "volume": data.get("volume", "unknown"),
            "bull_count": data.get("bull_count", 0),
            "bear_count": data.get("bear_count", 0),
            "key_themes": data.get("key_themes", [])[:5],
            "signal_quality": data.get("signal_quality", "unknown"),
            "contrarian_signal": data.get("contrarian_signal", False),
            "model": GROK_MODEL,
        }
        _cache[ticker] = (result, now)
        return result

    except json.JSONDecodeError:
        logger.warning("Grok non-JSON for %s", ticker)
        return {"ticker": ticker, "sentiment_score": None, "error": "json_parse_error"}
    except asyncio.TimeoutError:
        return {"ticker": ticker, "sentiment_score": None, "error": "timeout"}
    except Exception as e:
        logger.error("Grok failed for %s: %s", ticker, e)
        return {"ticker": ticker, "sentiment_score": None, "error": str(e)}
