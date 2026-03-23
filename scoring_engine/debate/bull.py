"""Bull agent — argues FOR buying the ticker."""

import logging

from scoring_engine.agents.base import OllamaClient, AnalystReport
from scoring_engine.debate.prompts import BULL_SYSTEM
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


async def argue_bull(ticker: str, reports: list[AnalystReport]) -> dict:
    """Bull agent produces arguments FOR buying."""
    prompt = _format_reports(ticker, reports)
    result = await _ollama.generate(
        system_prompt=BULL_SYSTEM,
        user_prompt=prompt,
        max_tokens=DEBATE_MAX_TOKENS,
        temperature=DEBATE_TEMPERATURE,
    )
    if result.get("_parse_error") or result.get("_error"):
        return {
            "argument": result.get("raw", "Bull analysis failed"),
            "catalysts": [],
            "target_upside_pct": 0,
            "conviction": 0,
        }
    return {
        "argument": result.get("argument", ""),
        "catalysts": result.get("catalysts", []),
        "target_upside_pct": result.get("target_upside_pct", 0),
        "conviction": result.get("conviction", 50),
    }
