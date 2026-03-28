"""Fundamental Analyst — rules-based scoring + Ollama narrative report."""

import logging

import httpx

from scoring_engine.agents.base import AnalystAgent, AnalystReport, OllamaClient
from scoring_engine.config import MARKET_DATA_URL

logger = logging.getLogger(__name__)

_client = httpx.AsyncClient(timeout=15.0)
_ollama = OllamaClient()

SYSTEM = "Tu es un analyste fondamental. Redige un rapport structure en francais, 5-8 lignes maximum. Pas de JSON, pas de markdown, pas de gras, pas de titres — juste du texte brut. Base-toi UNIQUEMENT sur les donnees fournies, n'invente aucun chiffre."


def _format_prompt(ticker: str, fundamentals: dict, analyst: dict, score: float) -> str:
    current = analyst.get("current_price") or fundamentals.get("current_price", 0)
    target = analyst.get("target_mean")
    upside = round((target - current) / current * 100, 1) if target and current else None

    fpe = fundamentals.get("forward_pe")
    rg = fundamentals.get("revenue_growth")
    margin = fundamentals.get("profit_margin")
    de = fundamentals.get("debt_to_equity")
    roe = fundamentals.get("return_on_equity")

    return (
        f"Ticker: {ticker} | Prix: ${current or '?'}\n"
        f"Score fondamental: {score:+.2f}\n"
        f"P/E forward: {f'{fpe:.1f}' if fpe else '?'} | "
        f"Croissance CA: {f'{rg*100:.0f}%' if rg is not None else '?'} | "
        f"Marge beneficiaire: {f'{margin*100:.0f}%' if margin is not None else '?'}\n"
        f"Dette/equity: {f'{de:.0f}%' if de is not None else '?'} | "
        f"ROE: {f'{roe*100:.0f}%' if roe is not None else '?'}\n"
        f"Target analystes: ${target or '?'} ({f'+{upside:.0f}%' if upside else '?'})\n\n"
        f"Redige un rapport couvrant: 1) Valorisation (le prix est-il justifie par les benefices ?) "
        f"2) Croissance (le chiffre d'affaires progresse-t-il ?) "
        f"3) Sante financiere (dette gerable ? entreprise rentable ?) "
        f"4) Ce que pensent les analystes de Wall Street"
    )


class FundamentalAnalyst(AnalystAgent):
    name = "fundamental"

    async def analyze(self, ticker: str, context: dict) -> AnalystReport:
        fundamentals = context.get("fundamentals") or {}
        analyst = context.get("analyst") or {}

        if not fundamentals:
            return AnalystReport(
                agent_name=self.name, ticker=ticker,
                score=0, confidence=0, summary="No fundamental data",
            )

        score = 0.0
        reasons = []

        # 1. Valuation: forward P/E < 25
        fpe = fundamentals.get("forward_pe")
        if fpe and fpe > 0:
            if fpe < 25:
                score += 0.2
                reasons.append(f"P/E forward {fpe:.1f} raisonnable")
            elif fpe > 40:
                score -= 0.2
                reasons.append(f"P/E forward {fpe:.1f} eleve")

        # 2. Growth: revenue growth > 5%
        rg = fundamentals.get("revenue_growth")
        if rg is not None:
            if rg > 0.05:
                score += 0.2
                reasons.append(f"Croissance CA {rg*100:.0f}%")
            elif rg < 0:
                score -= 0.15
                reasons.append(f"CA en baisse {rg*100:.0f}%")

        # 3. Profitability: profit margin > 15%
        margin = fundamentals.get("profit_margin")
        if margin is not None:
            if margin > 0.15:
                score += 0.15
                reasons.append(f"Marge {margin*100:.0f}%")
            elif margin < 0.05:
                score -= 0.15
                reasons.append(f"Marge faible {margin*100:.0f}%")

        # 4. Leverage: debt/equity < 100%
        de = fundamentals.get("debt_to_equity")
        if de is not None:
            if de < 100:
                score += 0.15
                reasons.append(f"Dette/equity {de:.0f}%")
            elif de > 200:
                score -= 0.15
                reasons.append(f"Dette elevee {de:.0f}%")

        # 5. Efficiency: ROE > 15%
        roe = fundamentals.get("return_on_equity")
        if roe is not None:
            if roe > 0.15:
                score += 0.15
                reasons.append(f"ROE {roe*100:.0f}%")
            elif roe < 0.05:
                score -= 0.1

        # 6. Analyst upside > 5%
        current = analyst.get("current_price") or fundamentals.get("current_price", 0)
        target = analyst.get("target_mean")
        if target and current and current > 0:
            upside = (target - current) / current
            if upside > 0.05:
                score += 0.15
                reasons.append(f"Target analystes +{upside*100:.0f}%")
            elif upside < -0.05:
                score -= 0.15
                reasons.append(f"Target analystes {upside*100:.0f}%")

        score = max(-1.0, min(1.0, score))

        # Ollama narrative report
        result = await _ollama.generate(
            system_prompt=SYSTEM,
            user_prompt=_format_prompt(ticker, fundamentals, analyst, score),
            max_tokens=300,
            temperature=0.3,
        )
        narrative = result.get("raw", result.get("summary", ""))
        if not narrative or result.get("_error"):
            narrative = "; ".join(reasons[:3]) if reasons else "Rapport fondamental indisponible"

        return AnalystReport(
            agent_name=self.name,
            ticker=ticker,
            score=round(score, 2),
            confidence=min(100, int(abs(score) * 100)),
            summary=narrative,
            metrics={
                "forward_pe": fpe,
                "revenue_growth": rg,
                "profit_margin": margin,
                "debt_to_equity": de,
                "return_on_equity": roe,
                "analyst_target": target,
                "analyst_upside": round((target - current) / current * 100, 1) if target and current else None,
            },
        )
