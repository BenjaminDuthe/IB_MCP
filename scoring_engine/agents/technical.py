"""Technical Analyst — rules-based score + Ollama narrative report."""

from scoring_engine.agents.base import AnalystAgent, AnalystReport, OllamaClient
from scoring_engine.scorer import compute_score

_ollama = OllamaClient()

SYSTEM = "Tu es un analyste technique. Redige un rapport structure en francais, 5-8 lignes maximum. Pas de JSON, pas de markdown, pas de gras, pas de titres — juste du texte brut. Base-toi UNIQUEMENT sur les donnees fournies, n'invente aucun chiffre."


def _format_prompt(ticker: str, technicals: dict, score_data: dict) -> str:
    ma = technicals.get("moving_averages", {})
    macd = technicals.get("macd", {}) or {}
    boll = technicals.get("bollinger", {}) or {}
    stoch = technicals.get("stochastic", {}) or {}
    vol = technicals.get("volume", {}) or {}
    vals = score_data.get("values", {})
    filters = score_data.get("filters", {})
    active = score_data.get("active_signals", [])

    f_str = " | ".join(f"{'OK' if v else 'NON'} {k}" for k, v in filters.items())
    sig_str = ", ".join(s["name"] for s in active) if active else "Aucun"

    return (
        f"Ticker: {ticker} | Prix: ${technicals.get('price', '?')}\n"
        f"Score: {score_data.get('score', '?')}/5 | Filtres: {f_str}\n"
        f"RSI(14): {technicals.get('rsi_14', '?')} | MACD: {macd.get('signal_type', '?')} (hist: {macd.get('histogram', '?')})\n"
        f"Stochastique K: {stoch.get('k', '?')} | Bollinger: {boll.get('position', '?')}\n"
        f"SMA20: ${ma.get('sma_20', '?')} | SMA50: ${ma.get('sma_50', '?')} | SMA200: ${ma.get('sma_200', '?')}\n"
        f"Trend MA: {ma.get('trend', '?')} | ATR relative: {vals.get('atr_relative', '?')}% | Volume: {vol.get('relative', '?')}x\n"
        f"Trend 5j: {vals.get('trend_5d', '?')}%\n"
        f"Signaux actifs: {sig_str}\n\n"
        f"Redige un rapport couvrant: 1) Tendance et pourquoi 2) Momentum (RSI+MACD+stoch ensemble) "
        f"3) Niveaux cles (supports, resistances) 4) Risque technique principal"
    )


class TechnicalAnalyst(AnalystAgent):
    name = "technical"

    async def analyze(self, ticker: str, context: dict) -> AnalystReport:
        technicals = context["technicals"]
        score_data = context.get("score_data") or compute_score(ticker, technicals)

        raw_score = score_data["score"]
        normalized = (raw_score - 2.5) / 2.5

        # Ollama narrative report
        result = await _ollama.generate(
            system_prompt=SYSTEM,
            user_prompt=_format_prompt(ticker, technicals, score_data),
            max_tokens=300,
            temperature=0.3,
        )
        narrative = result.get("raw", "")
        if not narrative or result.get("_error"):
            narrative = technicals.get("summary", "Rapport technique indisponible")

        return AnalystReport(
            agent_name=self.name,
            ticker=ticker,
            score=round(normalized, 2),
            confidence=raw_score * 20,
            summary=narrative,
            metrics={
                "binary_score": raw_score,
                "filters": score_data["filters"],
                "values": score_data["values"],
            },
        )
