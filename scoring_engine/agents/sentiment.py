"""Sentiment Analyst — wraps the existing combined sentiment endpoint."""

from scoring_engine.agents.base import AnalystAgent, AnalystReport


class SentimentAnalyst(AnalystAgent):
    name = "sentiment"

    async def analyze(self, ticker: str, context: dict) -> AnalystReport:
        sentiment = context.get("sentiment") or {}
        unified = sentiment.get("unified_score")
        if unified is None:
            unified = 0
        unified = float(unified)
        label = sentiment.get("unified_label", "neutral")
        sources = sentiment.get("sources_used", [])

        return AnalystReport(
            agent_name=self.name,
            ticker=ticker,
            score=round(unified, 2),
            confidence=min(100, int(abs(unified) * 100)),
            summary=f"Sentiment {label} ({unified:+.2f}), {len(sources)} sources",
            metrics={
                "unified_score": unified,
                "unified_label": label,
                "sources_used": sources,
                "fear_greed": sentiment.get("fear_greed"),
            },
        )
