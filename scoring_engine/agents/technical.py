"""Technical Analyst — wraps the existing 5-filter binary scorer."""

from scoring_engine.agents.base import AnalystAgent, AnalystReport
from scoring_engine.scorer import compute_score


class TechnicalAnalyst(AnalystAgent):
    name = "technical"

    async def analyze(self, ticker: str, context: dict) -> AnalystReport:
        technicals = context["technicals"]
        score_data = compute_score(ticker, technicals)
        # Normalize 0-5 to -1/+1
        raw_score = score_data["score"]
        normalized = (raw_score - 2.5) / 2.5

        return AnalystReport(
            agent_name=self.name,
            ticker=ticker,
            score=round(normalized, 2),
            confidence=raw_score * 20,
            summary=technicals.get("summary", ""),
            metrics={
                "binary_score": raw_score,
                "filters": score_data["filters"],
                "values": score_data["values"],
            },
        )
