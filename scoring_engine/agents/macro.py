"""Macro Analyst — market regime detection + sector rotation."""

import logging

from scoring_engine.agents.base import AnalystAgent, AnalystReport
from scoring_engine.config import TICKER_SECTORS

logger = logging.getLogger(__name__)


def _detect_regime(vix: float | None) -> str:
    if vix is None:
        return "unknown"
    if vix < 15:
        return "bullish"
    if vix < 25:
        return "neutral"
    return "bearish"


class MacroAnalyst(AnalystAgent):
    name = "macro"

    async def analyze(self, ticker: str, context: dict) -> AnalystReport:
        macro = context.get("macro") or {}
        sectors = context.get("sectors") or {}

        markets = macro.get("markets", {})
        # Extract key indices
        vix = None
        sp500_change = None
        treasury_10y = None
        dxy = None

        for item in markets if isinstance(markets, list) else []:
            name = item.get("name", "").lower()
            if "vix" in name:
                vix = item.get("price") or item.get("value")
            elif "s&p" in name or "sp500" in name:
                sp500_change = item.get("change_pct")
            elif "10" in name and "year" in name.lower():
                treasury_10y = item.get("price") or item.get("value")

        # Handle dict format
        if isinstance(markets, dict):
            vix_data = markets.get("VIX") or markets.get("vix") or {}
            vix = vix_data.get("price") or vix_data.get("value") if isinstance(vix_data, dict) else None
            sp_data = markets.get("S&P 500") or markets.get("sp500") or {}
            sp500_change = sp_data.get("change_pct") if isinstance(sp_data, dict) else None

        regime = _detect_regime(vix)

        # Score based on regime
        regime_scores = {"bullish": 0.3, "neutral": 0.0, "bearish": -0.3, "unknown": 0.0}
        score = regime_scores.get(regime, 0.0)

        # Sector rotation bonus/malus
        ticker_sector = TICKER_SECTORS.get(ticker, "unknown")
        sector_data = sectors.get("sectors", [])
        sector_rank = None
        if sector_data and isinstance(sector_data, list):
            for i, s in enumerate(sector_data):
                s_name = (s.get("sector", "") or s.get("name", "")).lower()
                if ticker_sector.lower() in s_name:
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

        return AnalystReport(
            agent_name=self.name,
            ticker=ticker,
            score=round(score, 2),
            confidence=60 if regime != "unknown" else 20,
            summary=", ".join(reasons),
            metrics={
                "vix": vix,
                "market_regime": regime,
                "sp500_change_pct": sp500_change,
                "treasury_10y": treasury_10y,
                "ticker_sector": ticker_sector,
                "sector_rank": sector_rank,
            },
        )
