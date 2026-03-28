"""Macro Analyst — market regime detection + sector rotation + Ollama narrative."""

import logging

from scoring_engine.agents.base import AnalystAgent, AnalystReport, OllamaClient
from scoring_engine.config import TICKER_SECTORS

logger = logging.getLogger(__name__)

_ollama = OllamaClient()

SYSTEM = "Tu es un analyste macro-economique. Redige un rapport en francais, 3-5 lignes maximum. Pas de JSON, pas de markdown, pas de gras, pas de titres — juste du texte brut. Base-toi UNIQUEMENT sur les donnees fournies. Si une donnee est '?' ou manquante, dis-le clairement, n'invente rien."


# Map config sector names → API sector-performance names (exact lowercase)
_SECTOR_MAP = {
    "tech": "technology",
    "consumer": "consumer",           # matches both Consumer Discretionary & Staples
    "healthcare": "healthcare",
    "finance": "financials",
    "energy": "energy",
    "industrials": "industrials",
    "materials": "materials",
    "aerospace": "industrials",       # No aerospace ETF, closest is XLI
    "luxury": "consumer discretionary",
    "telecom": "communication",
}


def _detect_regime(vix: float | None) -> str:
    if vix is None:
        return "unknown"
    if vix < 15:
        return "bullish"
    if vix < 25:
        return "neutral"
    return "bearish"


def _format_prompt(ticker: str, regime: str, vix, sp500_change, treasury_10y, dxy, ticker_sector: str, sector_rank, total_sectors: int) -> str:
    return (
        f"Ticker: {ticker} | Secteur: {ticker_sector}\n"
        f"VIX: {vix if vix is not None else '?'} | Regime: {regime}\n"
        f"S&P500 variation jour: {f'{sp500_change:+.2f}%' if sp500_change is not None else '?'}\n"
        f"Taux 10 ans US: {f'{treasury_10y:.3f}%' if treasury_10y is not None else '?'} | "
        f"Dollar (DXY): {f'{dxy:.1f}' if dxy is not None else '?'}\n"
        f"Rang secteur: {f'{sector_rank}/{total_sectors}' if sector_rank else '?'}\n\n"
        f"Redige 3-5 lignes: contexte macro actuel, impact sur le secteur {ticker_sector}, "
        f"et ce que cela implique pour les actions de ce secteur."
    )


class MacroAnalyst(AnalystAgent):
    name = "macro"

    async def analyze(self, ticker: str, context: dict) -> AnalystReport:
        macro = context.get("macro") or {}
        sectors = context.get("sectors") or {}

        markets = macro.get("markets") or {}
        # Extract key indices
        vix = None
        sp500_change = None
        treasury_10y = None
        dxy = None

        if not isinstance(markets, (list, dict)):
            markets = {}

        for item in markets if isinstance(markets, list) else []:
            name = item.get("name", "").lower()
            sym = item.get("symbol", "").upper()
            if "vix" in name or sym == "^VIX":
                vix = item.get("price") or item.get("value")
            elif "s&p" in name or sym == "^GSPC":
                sp500_change = item.get("change_percent")
            elif ("10y" in name or "10 year" in name or sym == "^TNX"):
                treasury_10y = item.get("price") or item.get("value")
            elif "dollar" in name or sym == "DX-Y.NYB":
                dxy = item.get("price") or item.get("value")

        regime = _detect_regime(vix)

        # Score based on regime
        regime_scores = {"bullish": 0.3, "neutral": 0.0, "bearish": -0.3, "unknown": 0.0}
        score = regime_scores.get(regime, 0.0)

        # Sector rotation bonus/malus
        ticker_sector = TICKER_SECTORS.get(ticker, "unknown")
        search_sector = _SECTOR_MAP.get(ticker_sector, ticker_sector).lower()
        sector_data = sectors.get("sectors", [])
        sector_rank = None
        total_sectors = len(sector_data) if sector_data else 0
        if sector_data and isinstance(sector_data, list):
            for i, s in enumerate(sector_data):
                s_name = (s.get("sector", "") or s.get("name", "")).lower()
                if search_sector in s_name:
                    sector_rank = i + 1
                    total = len(sector_data)
                    # Top 3 = bonus, bottom 3 = malus
                    if sector_rank <= 3:
                        score += 0.2
                    elif sector_rank >= total - 2:
                        score -= 0.2
                    break

        score = max(-1.0, min(1.0, score))
        reasons = [f"Regime: {regime}"]
        if vix is not None:
            reasons.append(f"VIX: {vix:.1f}")
        if sector_rank is not None:
            reasons.append(f"Secteur {ticker_sector} rang {sector_rank}/{len(sector_data)}")

        # Ollama narrative report
        result = await _ollama.generate(
            system_prompt=SYSTEM,
            user_prompt=_format_prompt(ticker, regime, vix, sp500_change, treasury_10y, dxy, ticker_sector, sector_rank, total_sectors),
            max_tokens=200,
            temperature=0.3,
        )
        narrative = result.get("raw", result.get("summary", ""))
        if not narrative or result.get("_error"):
            narrative = ", ".join(reasons)

        return AnalystReport(
            agent_name=self.name,
            ticker=ticker,
            score=round(score, 2),
            confidence=60 if regime != "unknown" else 20,
            summary=narrative,
            metrics={
                "vix": vix,
                "market_regime": regime,
                "sp500_change_pct": sp500_change,
                "treasury_10y": treasury_10y,
                "dxy": dxy,
                "ticker_sector": ticker_sector,
                "sector_rank": sector_rank,
            },
        )
