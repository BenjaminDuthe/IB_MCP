"""Bear agent — argues AGAINST buying the ticker."""

import logging

from scoring_engine.agents.base import OllamaClient, AnalystReport
from scoring_engine.debate.prompts import BEAR_SYSTEM
from scoring_engine.config import DEBATE_MAX_TOKENS, DEBATE_TEMPERATURE

logger = logging.getLogger(__name__)

_ollama = OllamaClient()


def _format_reports(ticker: str, reports: list[AnalystReport]) -> str:
    lines = [f"Ticker: {ticker}\n"]
    for r in reports:
        lines.append(
            f"[{r.agent_name.upper()}] Score: {r.score:+.2f} | Confiance: {r.confidence}%\n"
            f"  {r.summary}\n"
            f"  Metrics: {r.metrics}\n"
        )
    return "\n".join(lines)


async def argue_bear(ticker: str, reports: list[AnalystReport]) -> dict:
    """Bear agent produces arguments AGAINST buying."""
    prompt = _format_reports(ticker, reports)
    result = await _ollama.generate(
        system_prompt=BEAR_SYSTEM,
        user_prompt=prompt,
        max_tokens=DEBATE_MAX_TOKENS,
        temperature=DEBATE_TEMPERATURE,
    )
    if result.get("_parse_error") or result.get("_error"):
        return {
            "argument": result.get("raw", "Bear analysis failed"),
            "risks": [],
            "target_downside_pct": 0,
            "conviction": 0,
        }
    return {
        "argument": result.get("argument", ""),
        "risks": result.get("risks", []),
        "target_downside_pct": result.get("target_downside_pct", 0),
        "conviction": result.get("conviction", 50),
    }
