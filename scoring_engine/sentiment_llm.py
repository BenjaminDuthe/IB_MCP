"""Ollama client for local LLM sentiment synthesis."""

import json
import logging

import httpx

from scoring_engine.config import OLLAMA_URL, OLLAMA_MODEL

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Tu es un analyste trading. On te donne des donnees techniques et sentiment "
    "pre-calculees pour un ticker. Reponds UNIQUEMENT avec un JSON valide, "
    "sans markdown, sans explication:\n"
    '{"verdict": "BUY" ou "SELL" ou "HOLD", '
    '"confidence": 0-100, '
    '"summary": "1 phrase en francais"}'
)


async def synthesize_verdict(
    ticker: str,
    score: int,
    technicals: dict,
    sentiment: dict | None,
) -> dict:
    """Call Ollama for a single-pass verdict synthesis.

    Returns {"verdict": str, "confidence": int, "summary": str}.
    """
    ma = technicals.get("moving_averages", {})
    macd = technicals.get("macd", {}) or {}

    prompt_parts = [
        f"Ticker: {ticker} | Prix: {technicals.get('price', '?')} | Score: {score}/5",
        f"RSI: {technicals.get('rsi_14', '?')} | MACD: {macd.get('signal_type', '?')} | Trend MA: {ma.get('trend', '?')}",
        f"Trend 5j: {technicals.get('trend_5d', '?')}%",
    ]
    if sentiment:
        prompt_parts.append(
            f"Sentiment unifie: {sentiment.get('unified_score', '?')} ({sentiment.get('unified_label', '?')})"
        )
        fg = sentiment.get("fear_greed")
        if fg:
            prompt_parts.append(f"Fear & Greed: {fg}")

    prompt = "\n".join(prompt_parts)

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "system": SYSTEM_PROMPT,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": 120, "temperature": 0.3},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            raw_text = data.get("response", "").strip()

            # Try to extract JSON from response
            text = raw_text
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            parsed = json.loads(text)
            return {
                "verdict": parsed.get("verdict", "HOLD"),
                "confidence": int(parsed.get("confidence", 50)),
                "summary": parsed.get("summary", raw_text[:200]),
            }
    except json.JSONDecodeError:
        logger.warning("Ollama returned non-JSON for %s: %s", ticker, raw_text[:200])
        return {"verdict": "HOLD", "confidence": 0, "summary": raw_text[:200]}
    except Exception as e:
        logger.error("Ollama inference failed for %s: %s", ticker, e)
        return {"verdict": "HOLD", "confidence": 0, "summary": f"LLM error: {e}"}
