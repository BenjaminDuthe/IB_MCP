"""Sentiment Analyst — unified sentiment score + Ollama narrative report."""

from scoring_engine.agents.base import AnalystAgent, AnalystReport, OllamaClient

_ollama = OllamaClient()

SYSTEM = "Tu es un analyste sentiment de marche. Redige un rapport en francais, 3-5 lignes maximum. Pas de JSON, pas de markdown, pas de gras, pas de titres — juste du texte brut. Base-toi UNIQUEMENT sur les donnees fournies, n'invente rien."


def _format_prompt(ticker: str, unified: float, label: str, sources: list, sentiment: dict) -> str:
    macro_sent = sentiment.get("macro_sentiment") or {}
    fg = macro_sent.get("fear_greed_score")
    fg_label = macro_sent.get("fear_greed_label")
    rss = (sentiment.get("sources") or {}).get("rss") or {}
    article_count = rss.get("article_count", 0)

    fg_str = f"{fg} ({fg_label})" if fg is not None else "?"

    return (
        f"Ticker: {ticker}\n"
        f"Score sentiment unifie: {unified:+.2f} ({label})\n"
        f"Sources: {len(sources)} ({', '.join(sources) if sources else 'aucune'})\n"
        f"Fear & Greed Index: {fg_str}\n"
        f"Articles RSS recents: {article_count}\n\n"
        f"Redige 3-5 lignes: opinion actuelle du marche sur cette action, "
        f"evolution recente du sentiment, et fiabilite de ces indicateurs."
    )


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

        # Ollama narrative report
        result = await _ollama.generate(
            system_prompt=SYSTEM,
            user_prompt=_format_prompt(ticker, unified, label, sources, sentiment),
            max_tokens=200,
            temperature=0.3,
        )
        narrative = result.get("raw", result.get("summary", ""))
        if not narrative or result.get("_error"):
            narrative = f"Sentiment {label} ({unified:+.2f}), {len(sources)} sources"

        return AnalystReport(
            agent_name=self.name,
            ticker=ticker,
            score=round(unified, 2),
            confidence=min(100, int(abs(unified) * 100)),
            summary=narrative,
            metrics={
                "unified_score": unified,
                "unified_label": label,
                "sources_used": sources,
                "fear_greed": (sentiment.get("macro_sentiment") or {}).get("fear_greed_score"),
            },
        )
