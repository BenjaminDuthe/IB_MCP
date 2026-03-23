"""Debate facilitator — evaluates bull + bear arguments, produces final verdict."""

import logging

from scoring_engine.agents.base import OllamaClient, AnalystReport
from scoring_engine.debate.prompts import FACILITATOR_SYSTEM
from scoring_engine.config import DEBATE_MAX_TOKENS, DEBATE_TEMPERATURE

logger = logging.getLogger(__name__)

_ollama = OllamaClient()


async def evaluate(
    ticker: str,
    bull_case: dict,
    bear_case: dict,
    reports: list[AnalystReport],
) -> dict:
    """Facilitator evaluates both sides and produces verdict."""
    scores_summary = "\n".join(
        f"  {r.agent_name}: {r.score:+.2f} ({r.confidence}%)"
        for r in reports
    )

    prompt = (
        f"Ticker: {ticker}\n\n"
        f"--- SCORES ANALYSTES ---\n{scores_summary}\n\n"
        f"--- ARGUMENTAIRE HAUSSIER (conviction: {bull_case.get('conviction', 0)}%) ---\n"
        f"{bull_case.get('argument', 'N/A')}\n"
        f"Catalyseurs: {bull_case.get('catalysts', [])}\n"
        f"Objectif hausse: {bull_case.get('target_upside_pct', 0):+.1f}%\n\n"
        f"--- ARGUMENTAIRE BAISSIER (conviction: {bear_case.get('conviction', 0)}%) ---\n"
        f"{bear_case.get('argument', 'N/A')}\n"
        f"Risques: {bear_case.get('risks', [])}\n"
        f"Objectif baisse: {bear_case.get('target_downside_pct', 0):.1f}%\n"
    )

    result = await _ollama.generate(
        system_prompt=FACILITATOR_SYSTEM,
        user_prompt=prompt,
        max_tokens=DEBATE_MAX_TOKENS,
        temperature=DEBATE_TEMPERATURE,
    )

    if result.get("_parse_error") or result.get("_error"):
        return {
            "verdict": "HOLD",
            "confidence": 0,
            "summary": result.get("raw", "Facilitator failed")[:200],
            "bull_strength": bull_case.get("conviction", 0),
            "bear_strength": bear_case.get("conviction", 0),
            "key_factor": "Debate inconclusive",
        }

    return {
        "verdict": result.get("verdict", "HOLD"),
        "confidence": int(result.get("confidence", 50)),
        "summary": result.get("summary", ""),
        "bull_strength": int(result.get("bull_strength", 50)),
        "bear_strength": int(result.get("bear_strength", 50)),
        "key_factor": result.get("key_factor", ""),
    }
