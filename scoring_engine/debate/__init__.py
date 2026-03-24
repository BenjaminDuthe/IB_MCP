"""Bull/Bear debate mechanism — 3 Ollama calls per ticker (bull+bear parallel)."""

import asyncio
import logging
import time

from scoring_engine.agents.base import AnalystReport
from scoring_engine.debate.bull import argue_bull
from scoring_engine.debate.bear import argue_bear
from scoring_engine.debate.facilitator import evaluate

logger = logging.getLogger(__name__)


async def run_debate(ticker: str, reports: list[AnalystReport]) -> dict:
    """Run 3-round debate: bull → bear → facilitator.

    Returns dict with verdict, confidence, summary, arguments, and timing.
    """
    start = time.time()

    # Round 1+2: Bull and Bear argue in parallel
    bull_case, bear_case = await asyncio.gather(
        argue_bull(ticker, reports),
        argue_bear(ticker, reports),
    )
    logger.info("Debate %s: Bull conviction=%d%% Bear conviction=%d%%",
                ticker, bull_case.get("conviction", 0), bear_case.get("conviction", 0))

    # Round 3: Facilitator evaluates
    verdict = await evaluate(ticker, bull_case, bear_case, reports)
    duration = time.time() - start

    logger.info(
        "Debate %s: %s (%d%%) in %.1fs | Bull=%d%% Bear=%d%%",
        ticker, verdict["verdict"], verdict["confidence"],
        duration, verdict["bull_strength"], verdict["bear_strength"],
    )

    return {
        **verdict,
        "bull_argument": bull_case.get("argument", ""),
        "bull_catalysts": bull_case.get("catalysts", []),
        "bear_argument": bear_case.get("argument", ""),
        "bear_risks": bear_case.get("risks", []),
        "debate_rounds": 3,
        "debate_duration_seconds": round(duration, 1),
    }
