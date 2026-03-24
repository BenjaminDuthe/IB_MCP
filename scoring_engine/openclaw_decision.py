"""OpenClaw (Claude) decision maker — receives analyst reports, returns verdicts."""

import json
import logging
import os

import httpx

logger = logging.getLogger(__name__)

OPENCLAW_API_URL = os.environ.get("OPENCLAW_API_URL", "http://192.168.1.125:18789/v1/responses")
OPENCLAW_TOKEN = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "")

DECISION_PROMPT = """Tu es le comite d'investissement d'un fonds. Tu recois les rapports de 4 analystes (technique, fondamental, macro, sentiment) pour chaque ticker.

TON ROLE : peser le pour et le contre de chaque ticker comme un vrai comite. Pour chaque action, argumente brievement les 2 cotes avant de trancher.

REGLES :
1. Score technique 0-2/5 → NE PEUT PAS etre BUY sauf fondamentaux exceptionnels (CA>50% ET P/E<15)
2. Max 3 BUY par secteur (tech = 11 tickers, attention surexposition)
3. Conviction 0-100 : sois honnete. Donnees insuffisantes (sentiment=0, macro=unknown) = conviction basse
4. Un HOLD n'est pas un echec — c'est la decision la plus frequente d'un bon comite

Reponds UNIQUEMENT en JSON valide (pas de markdown, pas de commentaires) :
{
  "rankings": [
    {
      "rank": 1,
      "ticker": "NVDA",
      "verdict": "BUY",
      "conviction": 78,
      "bull_case": "1 phrase : pourquoi acheter",
      "bear_case": "1 phrase : pourquoi ne pas acheter",
      "reason": "1 phrase : le facteur decisif qui fait pencher la balance",
      "risk": "le risque principal a surveiller"
    }
  ],
  "portfolio_alerts": ["alerte si surexposition sectorielle, correlation, ou risque macro"],
  "market_comment": "1-2 phrases sur le contexte macro du jour"
}

Classe TOUS les tickers du meilleur au pire. BUY = opportunite claire avec conviction >60. HOLD = pas de signal clair. SELL = eviter/sortir."""


async def get_openclaw_verdicts(ticker_reports: list[dict]) -> dict | None:
    """Send all ticker reports to OpenClaw and get portfolio-level verdicts."""
    if not OPENCLAW_TOKEN:
        logger.warning("OPENCLAW_GATEWAY_TOKEN not set, skipping decision")
        return None

    # Format reports into a structured prompt
    lines = []
    for tr in ticker_reports:
        ticker = tr.get("ticker", "?")
        score = tr.get("score", {})
        reports = tr.get("analyst_reports", [])
        llm = tr.get("llm", {})

        lines.append(f"\n=== {ticker} (Score technique: {score.get('score', '?')}/5) ===")

        for r in reports:
            name = r.get("agent_name", "?")
            lines.append(f"  [{name.upper()}] Score: {r.get('score', 0):+.2f} | {r.get('summary', '')[:120]}")
            metrics = r.get("metrics", {})
            if metrics and name == "fundamental":
                parts = []
                if metrics.get("forward_pe"): parts.append(f"P/E={metrics['forward_pe']:.0f}")
                if metrics.get("revenue_growth") is not None: parts.append(f"CA={metrics['revenue_growth']*100:+.0f}%")
                if metrics.get("profit_margin") is not None: parts.append(f"Marge={metrics['profit_margin']*100:.0f}%")
                if metrics.get("analyst_upside") is not None: parts.append(f"Target={metrics['analyst_upside']:+.0f}%")
                if parts:
                    lines.append(f"    Metrics: {', '.join(parts)}")

        filters = score.get("filters", {})
        if filters:
            f_str = " ".join(("Y" if v else "N") for v in filters.values())
            lines.append(f"  Filtres: {f_str} ({score.get('score', 0)}/5)")

        if llm.get("summary"):
            lines.append(f"  LLM: {llm['summary'][:100]}")

    prompt_text = "\n".join(lines)

    payload = {
        "model": "openclaw",
        "input": prompt_text,
        "instructions": DECISION_PROMPT,
    }

    headers = {
        "Authorization": f"Bearer {OPENCLAW_TOKEN}",
        "Content-Type": "application/json",
        "x-openclaw-session-key": "trading-decision",
    }

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(OPENCLAW_API_URL, json=payload, headers=headers)

            if resp.status_code != 200:
                logger.error("OpenClaw decision error %d: %s", resp.status_code, resp.text[:300])
                return None

            data = resp.json()

            # Extract text from OpenClaw response
            output_text = ""
            output = data.get("output", [])
            if isinstance(output, list):
                for item in output:
                    if isinstance(item, dict) and item.get("type") == "message":
                        for content in item.get("content", []):
                            if isinstance(content, dict) and content.get("type") == "output_text":
                                output_text = content.get("text", "")
                                break
            elif isinstance(output, str):
                output_text = output
            if not output_text:
                output_text = data.get("text", "") or data.get("content", "")

            # Parse JSON
            text = output_text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()

            return json.loads(text)

    except json.JSONDecodeError as e:
        logger.warning("OpenClaw returned non-JSON: %s | raw: %s", e, output_text[:300])
        return None
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        logger.error("OpenClaw network error: %s", e)
        return None
    except Exception as e:
        logger.error("OpenClaw decision failed: %s", e)
        return None
