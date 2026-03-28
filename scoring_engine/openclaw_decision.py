"""OpenClaw (Claude) decision maker — receives analyst reports, returns verdicts."""

import json
import logging
import os

import httpx

logger = logging.getLogger(__name__)

OPENCLAW_API_URL = os.environ.get("OPENCLAW_API_URL", "http://192.168.1.125:18789/v1/responses")
OPENCLAW_TOKEN = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "")

DECISION_PROMPT = """Tu es le comite d'investissement d'un fonds. Tu recois les rapports de 4-5 analystes (technique, fondamental, macro, sentiment, et parfois GROK_X qui analyse le sentiment temps reel sur X/Twitter) pour chaque ticker.

IMPORTANT sur GROK_X : quand present, ce rapport confronte notre analyse avec le sentiment reel des traders sur X. Si GROK_X indique "DIVERGENCE: contredit" avec "contrarian_signal: OUI", c'est un signal fort — les traders sur X voient quelque chose que nos indicateurs ne captent pas. Pese cette information dans ta decision.

TON ROLE : peser le pour et le contre de chaque ticker comme un vrai comite d'investissement. Explique simplement, comme si tu parlais a quelqu'un qui debute en bourse.

REGLES :
1. Un ticker avec 0 signal actif (0/6) NE PEUT PAS etre BUY — aucun signal backteste ne le soutient
1b. Un ticker avec score technique 0-2/5 ne peut etre BUY que s'il a au moins 2 signaux actifs
2. Max 3 BUY par secteur (tech a beaucoup de tickers, attention surexposition)
3. Conviction = le meilleur win rate backteste parmi les signaux actifs. NE L'INVENTE PAS. Si le meilleur signal actif a un win rate de 63%, la conviction est 63%. Si aucun signal actif, conviction = 50% (hasard) = HOLD
4. Un HOLD n'est pas un echec — c'est la decision la plus frequente d'un bon comite
5. Pour chaque BUY, estime un horizon temporel : en combien de temps le prix cible peut etre atteint ? Utilise le trend 5 jours, la volatilite (ATR), le momentum technique et le contexte macro pour estimer. Indique une fourchette realiste.
6. Ecris les raisons de facon simple et comprehensible, evite le jargon technique.

Reponds UNIQUEMENT en JSON valide (pas de markdown, pas de commentaires) :
{
  "rankings": [
    {
      "rank": 1,
      "ticker": "NVDA",
      "verdict": "BUY ou WATCH ou HOLD ou SELL",
      "conviction": 78,
      "bull_case": "Pourquoi acheter (1-2 phrases simples)",
      "bear_case": "Pourquoi hesiter (1-2 phrases simples)",
      "reason": "Le facteur decisif qui fait pencher la balance",
      "risk": "Le risque principal a surveiller",
      "target_price": 200.0,
      "horizon": "4-6 semaines si la tendance actuelle se maintient, 2-3 mois dans un scenario prudent"
    }
  ],
  "portfolio_alerts": ["alerte si surexposition sectorielle, correlation, ou risque macro"],
  "market_comment": "1-2 phrases simples sur le contexte economique general"
}

Classe TOUS les tickers du meilleur au pire.
BUY = signal actif confirme, conviction >= 60.
WATCH = signal mean reversion detecte mais l'action baisse encore — TU surveilles en interne et tu previens quand ca passe en BUY.
HOLD = pas de signal.
SELL = eviter/sortir.

IMPORTANT pour les WATCH : ne les mets PAS dans le classement principal. Mentionne-les dans market_comment en disant : "X tickers a surveiller (noms) — signal mean reversion en attente de confirmation". Quand un ancien WATCH passe en BUY, signale-le dans portfolio_alerts avec "NOUVEAU : [ticker] passe de A SURVEILLER a ACHAT"."""


async def get_openclaw_verdicts(ticker_reports: list[dict]) -> dict | None:
    """Send all ticker reports to OpenClaw and get portfolio-level verdicts."""
    if not OPENCLAW_TOKEN:
        logger.warning("OPENCLAW_GATEWAY_TOKEN not set, skipping decision")
        return None

    # Format reports into a structured prompt
    # Include calibration data so Claude uses real win rates
    from scoring_engine.backtest.calibration import load_calibration
    cal = load_calibration()
    lines = ["\n=== DONNEES DE CALIBRATION (basees sur 10 ans de backtest) ==="]
    for score_key in sorted(cal.keys()):
        parts = []
        for h_key, data in cal[score_key].items():
            if isinstance(data, dict):
                parts.append(f"{h_key}: {data.get('win_rate', '?')}% gagnant, rendement moyen {data.get('avg_return', '?')}%")
        if parts:
            lines.append(f"  {score_key}: {' | '.join(parts)}")
    lines.append("UTILISE ces win rates comme base de conviction — ne les invente pas.\n")

    for tr in ticker_reports:
        ticker = tr.get("ticker", "?")
        score = tr.get("score", {})
        reports = tr.get("analyst_reports", [])
        llm = tr.get("llm", {})

        active_sigs = score.get("active_signals", [])
        best_wr = score.get("best_win_rate", 50)
        composite = score.get("composite_score", 0)
        lines.append(f"\n=== {ticker} (Signaux actifs: {composite}/{score.get('max_composite', 6)}, meilleur win rate: {best_wr}%) ===")

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

        # Active strategy signals with win rates
        if active_sigs:
            lines.append("  SIGNAUX ACTIFS:")
            for sig in active_sigs:
                lines.append(f"    ✅ {sig['name']} (win rate: {sig['win_rate_60d']}% à 60j)")
        else:
            lines.append("  AUCUN SIGNAL ACTIF")

        # Watch signals (setup detected but not confirmed)
        watch_sigs = score.get("watch_signals", [])
        if watch_sigs:
            lines.append("  À SURVEILLER:")
            for ws in watch_sigs:
                lines.append(f"    👀 {ws['name']} — {ws['condition']}")

        # Grok X divergence analysis (only present in high fear + US tickers)
        grok = tr.get("grok_report")
        if grok and grok.get("sentiment_score") is not None:
            divergence = grok.get("divergence", "neutre")
            divergence_detail = grok.get("divergence_detail", "")
            grok_themes = ", ".join(grok.get("key_themes", []))
            contrarian = "OUI" if grok.get("contrarian_signal") else "non"
            lines.append(f"  [GROK_X] Score: {grok['sentiment_score']:+.2f} | DIVERGENCE: {divergence} — {divergence_detail}")
            lines.append(f"    Themes X: {grok_themes} | Signal contrarian: {contrarian} | Qualite: {grok.get('signal_quality', '?')}")

        filters = score.get("filters", {})
        if filters:
            filters_status = " ".join(("Y" if v else "N") for v in filters.values())
            lines.append(f"  Filtres: {filters_status} ({score.get('score', 0)}/5)")

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
        "x-openclaw-session-key": "agent:trading:main",
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
