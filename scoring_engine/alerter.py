"""Alert dispatcher: Discord webhooks with rich embeds."""

import logging
from datetime import datetime

import httpx

from scoring_engine.config import DISCORD_WEBHOOK_URL

logger = logging.getLogger(__name__)

_client = httpx.AsyncClient(timeout=15.0)

# Discord embed colors
COLOR_BUY = 0x00C853    # green
COLOR_SELL = 0xFF1744    # red
COLOR_HOLD = 0xFFA000    # amber
COLOR_INFO = 0x2196F3    # blue


async def send_discord_embed(embeds: list[dict]) -> bool:
    """Send rich embed to Discord #signaux-agent channel."""
    if not DISCORD_WEBHOOK_URL:
        return False
    try:
        resp = await _client.post(
            DISCORD_WEBHOOK_URL,
            json={"embeds": embeds, "username": "Trading Agent"},
        )
        if resp.status_code in (200, 204):
            return True
        logger.warning("Discord send failed: %d %s", resp.status_code, resp.text[:200])
        return False
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        logger.error("Discord network error: %s", e)
        return False
    except Exception as e:
        logger.error("Discord unexpected error: %s", e)
        return False


async def alert_signal(
    ticker: str, score: int, price: float, verdict: str,
    confidence: int, summary: str, filters: dict | None = None,
    values: dict | None = None,
    analyst_reports: list[dict] | None = None,
    risk: dict | None = None,
    bull_case: str = "", bear_case: str = "", openclaw_risk: str = "",
) -> None:
    """Send signal alert to Discord #signaux-agent."""
    emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚠️"}.get(verdict, "❓")
    color = {"BUY": COLOR_BUY, "SELL": COLOR_SELL, "HOLD": COLOR_HOLD}.get(verdict, COLOR_INFO)

    filter_lines = []
    if filters:
        for fname, passed in filters.items():
            mark = "✅" if passed else "❌"
            label = fname.replace("_", " ").title()
            filter_lines.append(f"{mark} {label}")

    fields = [
        {"name": "Score", "value": f"**{score}/5**", "inline": True},
        {"name": "Confiance", "value": f"{confidence}%", "inline": True},
        {"name": "Prix", "value": f"${price:.2f}", "inline": True},
    ]
    if values:
        rsi = values.get("rsi_14")
        atr = values.get("atr_relative")
        trend = values.get("trend_5d")
        tech_parts = []
        if rsi is not None:
            tech_parts.append(f"RSI: {rsi}")
        if atr is not None:
            tech_parts.append(f"ATR: {atr}%")
        if trend is not None:
            tech_parts.append(f"Trend 5j: {trend:+.1f}%")
        if tech_parts:
            fields.append({"name": "Indicateurs", "value": " | ".join(tech_parts), "inline": False})
    if filter_lines:
        fields.append({"name": "Filtres (5)", "value": "\n".join(filter_lines), "inline": False})

    # Analyst scores row (if available)
    if analyst_reports:
        agent_parts = []
        for ar in analyst_reports:
            name = ar.get("agent_name", "?")
            s = ar.get("score", 0)
            icon = {"technical": "📊", "fundamental": "📈", "macro": "🌍", "sentiment": "💬"}.get(name, "•")
            agent_parts.append(f"{icon} {name.title()}: {s:+.2f}")
        fields.append({"name": "Analystes", "value": " | ".join(agent_parts), "inline": False})

    # Bull/Bear from OpenClaw
    if bull_case:
        fields.append({"name": "🐂 Pour", "value": bull_case[:200], "inline": False})
    if bear_case:
        fields.append({"name": "🐻 Contre", "value": bear_case[:200], "inline": False})
    if openclaw_risk:
        fields.append({"name": "⚠️ Risque", "value": openclaw_risk[:150], "inline": False})

    # Position sizing (if risk data available)
    if risk and risk.get("position"):
        pos = risk["position"]
        fields.append({
            "name": "Position Suggérée",
            "value": f"{pos['shares']} actions (${pos['dollar_value']:.0f})",
            "inline": True,
        })
        fields.append({
            "name": "Risque Portfolio",
            "value": f"{pos['risk_pct']:.1f}% ({pos['method']})",
            "inline": True,
        })
    if risk and risk.get("warnings"):
        fields.append({
            "name": "⚠️ Warnings",
            "value": "\n".join(risk["warnings"][:3]),
            "inline": False,
        })

    footer = "Trading Agent v2 | Multi-Agent" if (analyst_reports or debate) else "Trading Agent | Scoring Engine"
    embed = {
        "title": f"{emoji} SIGNAL {verdict} — {ticker}",
        "description": summary,
        "color": color,
        "fields": fields[:25],  # Discord limit
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {"text": footer},
    }
    await send_discord_embed([embed])


async def alert_scan_summary(market: str, results: list[dict], openclaw_verdicts: dict | None = None) -> None:
    """Option C: compact ranking table + top 5 detailed embeds."""
    from scoring_engine.config import TICKER_INFO, TICKER_SECTORS, TICKER_DESCRIPTION

    valid = [r for r in results if not r.get("error") and r.get("score")]

    # Sort by openclaw rank if available, else by score
    if any(r.get("openclaw_rank") for r in valid):
        valid.sort(key=lambda r: r.get("openclaw_rank", 99))
    else:
        valid.sort(key=lambda r: (r["score"]["score"], r.get("llm", {}).get("confidence", 0)), reverse=True)

    if not valid:
        return

    # --- MESSAGE 1: Compact ranking table ---
    lines = []
    for rank, r in enumerate(valid, 1):
        s = r["score"]
        l = r.get("llm", {})
        ticker = s.get("ticker", "?")
        info = TICKER_INFO.get(ticker, {})
        name = info.get("name", ticker)[:16]
        flag = info.get("country", "")
        verdict = l.get("verdict", "?")
        conf = l.get("confidence", 0)
        price = s.get("price", 0)
        score = s.get("score", 0)

        # Analyst scores
        reports = {a["agent_name"]: a["score"] for a in r.get("analyst_reports", [])}
        fund = reports.get("fundamental", 0)
        tech = reports.get("technical", 0)

        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"` {rank:2d}`")
        v_emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡", "WATCH": "👀"}.get(verdict, "⚪")

        lines.append(
            f"{medal} **{name}** {flag}  {score}/5  {v_emoji}{verdict} {conf}%  ${price:.0f}  📈{fund:+.1f} 📊{tech:+.1f}"
        )

    # Market comment from OpenClaw
    market_comment = ""
    if openclaw_verdicts and openclaw_verdicts.get("market_comment"):
        market_comment = f"\n\n💬 *{openclaw_verdicts['market_comment']}*"

    # Portfolio alerts
    alerts_text = ""
    if openclaw_verdicts and openclaw_verdicts.get("portfolio_alerts"):
        alerts = openclaw_verdicts["portfolio_alerts"]
        if alerts:
            alerts_text = "\n\n⚠️ " + " | ".join(str(a) for a in alerts[:3])

    ranking_embed = {
        "title": f"📊 Scan {market} — {len(valid)} tickers",
        "description": "\n".join(lines) + market_comment + alerts_text,
        "color": COLOR_INFO,
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {"text": "Trading Agent v2 | Classement par OpenClaw (Claude & Grok)" if any(r.get("grok_report") for r in valid) else "Trading Agent v2 | Classement par OpenClaw (Claude)"},
    }
    await send_discord_embed([ranking_embed])

    # --- MESSAGE 2: Top 5 detailed embeds ---
    # Only show detailed cards for BUY verdicts
    # BUY cards only (conviction >= 60%). WATCH stays internal.
    buy_results = [r for r in valid if r.get("llm", {}).get("verdict") == "BUY" and r.get("llm", {}).get("confidence", 0) >= 60]
    if not buy_results:
        return

    embeds = []
    for rank, r in enumerate(buy_results, 1):
        s = r["score"]
        l = r.get("llm", {})
        ticker = s.get("ticker", "?")
        info = TICKER_INFO.get(ticker, {})
        name = info.get("name", ticker)
        flag = info.get("country", "")
        exchange = info.get("exchange", "")
        sector = TICKER_SECTORS.get(ticker, "")
        company_desc = TICKER_DESCRIPTION.get(ticker, "")
        conf = l.get("confidence", 0)
        price = s.get("price", 0)
        score = s.get("score", 0)

        # Description: company info + verdict
        desc = f"*{company_desc}*\n" if company_desc else ""
        desc += f"📍 {exchange} • {sector.title()}\n\n"
        desc += f"🟢 **ACHAT recommandé** ({conf}%) | Score {score}/5 | ${price:.2f}"

        fields = []

        # Analyst scores (vulgarisé)
        reports = r.get("analyst_reports", [])
        if reports:
            scores_map = {a["agent_name"]: a for a in reports}
            tech_s = scores_map.get("technical", {}).get("score", 0)
            fund_s = scores_map.get("fundamental", {}).get("score", 0)
            macro_s = scores_map.get("macro", {}).get("score", 0)
            sent_s = scores_map.get("sentiment", {}).get("score", 0)

            def _label(s):
                if s >= 0.5: return "très positive"
                if s >= 0.1: return "positive"
                if s > -0.1: return "neutre"
                if s > -0.5: return "négative"
                return "très négative"

            fields.append({
                "name": "📊 Nos 4 analystes",
                "value": (
                    f"📊 Analyse technique : {_label(tech_s)} ({tech_s:+.1f})\n"
                    f"📈 Santé financière : {_label(fund_s)} ({fund_s:+.1f})\n"
                    f"🌍 Contexte économique : {_label(macro_s)} ({macro_s:+.1f})\n"
                    f"💬 Opinion du marché : {_label(sent_s)} ({sent_s:+.1f})"
                ),
                "inline": False,
            })

        # Fundamentals (vulgarisé)
        for a in reports:
            if a.get("agent_name") == "fundamental" and a.get("metrics"):
                m = a["metrics"]
                parts = []
                if m.get("forward_pe"):
                    parts.append(f"Le cours vaut {m['forward_pe']:.0f}× les bénéfices")
                if m.get("revenue_growth") is not None:
                    parts.append(f"Chiffre d'affaires {m['revenue_growth']*100:+.0f}%")
                if m.get("profit_margin") is not None:
                    parts.append(f"Marge bénéficiaire {m['profit_margin']*100:.0f}%")
                # Target price avec horizon
                target = r.get("openclaw_target_price")
                horizon = r.get("openclaw_horizon", "")
                if target and price > 0:
                    upside = (target - price) / price * 100
                    target_text = f"Les analystes visent ${target:.0f} ({upside:+.0f}%)"
                    if horizon:
                        target_text += f"\n⏱️ {horizon}"
                    parts.append(target_text)
                elif m.get("analyst_upside") is not None:
                    parts.append(f"Les analystes visent {m['analyst_upside']:+.0f}% de hausse")
                if parts:
                    fields.append({"name": "📈 Chiffres clés", "value": "\n".join(parts), "inline": False})

        # Technicals (vulgarisé)
        vals = s.get("values", {})
        filters = s.get("filters", {})
        tech_lines = []
        rsi = vals.get("rsi_14")
        if rsi is not None:
            if rsi > 70: rsi_label = "suracheté (attention)"
            elif rsi < 30: rsi_label = "survendu (opportunité ?)"
            else: rsi_label = "zone neutre"
            tech_lines.append(f"RSI {rsi:.0f} — {rsi_label}")
        trend = vals.get("trend_5d")
        if trend is not None:
            tech_lines.append(f"L'action a {'pris' if trend > 0 else 'perdu'} {abs(trend):.1f}% sur 5 jours")
        if filters:
            filter_labels = {
                "price_above_sma20": "Au-dessus de sa moyenne 20 jours",
                "trend_5d_positive": "Tendance 5 jours positive",
                "rsi_below_threshold": "Pas en zone de surachat",
                "price_above_sma200": "Au-dessus de sa moyenne 200 jours",
                "atr_relative_ok": "Volatilité maîtrisée",
            }
            for k, v in filters.items():
                label = filter_labels.get(k, k)
                tech_lines.append(f"{'✅' if v else '❌'} {label}")
        if tech_lines:
            fields.append({"name": "📊 Signaux techniques", "value": "\n".join(tech_lines), "inline": False})

        # Bull case
        bull = r.get("bull_case", "")
        if bull:
            fields.append({"name": "🐂 Pourquoi acheter ?", "value": bull[:250], "inline": False})

        # Bear case
        bear = r.get("bear_case", "")
        if bear:
            fields.append({"name": "🐻 Pourquoi hésiter ?", "value": bear[:250], "inline": False})

        # Verdict
        reason = l.get("summary", "")
        if reason:
            fields.append({"name": "💡 Verdict", "value": reason[:300], "inline": False})

        # Risk
        risk_text = r.get("openclaw_risk", "")
        if risk_text:
            fields.append({"name": "⚠️ À surveiller", "value": risk_text[:200], "inline": False})

        embeds.append({
            "title": f"🟢 {name} ({ticker}) {flag}",
            "description": desc,
            "color": COLOR_BUY,
            "fields": fields[:10],
        })

    if embeds:
        embeds[-1]["timestamp"] = datetime.utcnow().isoformat()
        embeds[-1]["footer"] = {"text": f"Trading Agent v2 | {market} — {len(buy_results)} achat(s) recommandé(s)"}
        await send_discord_embed(embeds)


async def alert_daily_summary(summary: str) -> None:
    """Send end-of-day summary to Discord."""
    embed = {
        "title": "📊 Résumé Journalier",
        "description": summary[:4096],
        "color": COLOR_INFO,
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {"text": "Trading Agent | Résumé fin de journée"},
    }
    await send_discord_embed([embed])
