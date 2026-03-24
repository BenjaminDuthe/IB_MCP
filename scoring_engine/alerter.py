"""Alert dispatcher: Telegram + Discord webhooks with rich embeds."""

import logging
from datetime import datetime

import httpx

from scoring_engine.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DISCORD_WEBHOOK_URL

logger = logging.getLogger(__name__)

_client = httpx.AsyncClient(timeout=15.0)

# Discord embed colors
COLOR_BUY = 0x00C853    # green
COLOR_SELL = 0xFF1744    # red
COLOR_HOLD = 0xFFA000    # amber
COLOR_INFO = 0x2196F3    # blue


async def send_telegram(message: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.debug("Telegram not configured, skipping alert")
        return False
    try:
        resp = await _client.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
            },
        )
        if resp.status_code == 200:
            return True
        logger.warning("Telegram send failed: %d %s", resp.status_code, resp.text[:200])
        return False
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        logger.error("Telegram network error: %s", e)
        return False
    except Exception as e:
        logger.error("Telegram unexpected error: %s", e)
        return False


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
    values: dict | None = None, debate: dict | None = None,
    analyst_reports: list[dict] | None = None,
    risk: dict | None = None,
) -> None:
    """Send signal alert to Telegram and Discord #signaux-agent."""
    emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚠️"}.get(verdict, "❓")
    color = {"BUY": COLOR_BUY, "SELL": COLOR_SELL, "HOLD": COLOR_HOLD}.get(verdict, COLOR_INFO)

    # --- Telegram (HTML) ---
    tg_msg = (
        f"{emoji} <b>SIGNAL {verdict}</b> — {ticker}\n\n"
        f"  Score: <b>{score}/5</b> | Confiance: {confidence}%\n"
        f"  Prix: ${price:.2f}\n"
        f"  {summary}"
    )
    await send_telegram(tg_msg)

    # --- Discord (rich embed) ---
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

    # Debate section (if available)
    if debate:
        bull_arg = debate.get("bull_argument", "")[:200]
        bear_arg = debate.get("bear_argument", "")[:200]
        key_factor = debate.get("key_factor", "")
        if bull_arg:
            fields.append({"name": "🐂 Argument Haussier", "value": bull_arg, "inline": False})
        if bear_arg:
            fields.append({"name": "🐻 Argument Baissier", "value": bear_arg, "inline": False})
        if key_factor:
            fields.append({"name": "⚖️ Facteur Décisif", "value": key_factor, "inline": False})

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


async def alert_scan_summary(market: str, results: list[dict]) -> None:
    """Send rich market scan summary to Discord — ranked, with full company info."""
    from scoring_engine.config import TICKER_INFO, TICKER_SECTORS

    # Filter valid results and sort by score descending (ranking)
    valid = [r for r in results if not r.get("error") and r.get("score")]
    valid.sort(key=lambda r: (r["score"]["score"], r.get("llm", {}).get("confidence", 0)), reverse=True)

    if not valid:
        return

    embeds = []
    for rank, r in enumerate(valid, 1):
        s = r["score"]
        l = r.get("llm", {})
        db = r.get("debate", {})
        reports = r.get("analyst_reports", [])
        risk = r.get("risk")
        score = s.get("score", 0)
        price = s.get("price", 0)
        verdict = l.get("verdict", "?")
        conf = l.get("confidence", 0)
        ticker = s.get("ticker", "?")

        # Company metadata
        info = TICKER_INFO.get(ticker, {})
        name = info.get("name", ticker)
        flag = info.get("country", "")
        exchange = info.get("exchange", "")
        sector = TICKER_SECTORS.get(ticker, "")

        # Rank medal
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")

        # Verdict emoji + color
        v_emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(verdict, "⚪")
        color = {"BUY": COLOR_BUY, "SELL": COLOR_SELL, "HOLD": COLOR_HOLD}.get(verdict, COLOR_INFO)

        # Title: rank + company name + flag
        title = f"{medal} {name} ({ticker}) {flag}"

        # Description: verdict + price + exchange + sector
        desc = f"{v_emoji} **{verdict}** ({conf}%) | Score **{score}/5** | ${price:.2f}\n"
        desc += f"📍 {exchange} | {sector.title()}"

        fields = []

        # Analyst scores compact
        if reports:
            scores_map = {a["agent_name"]: a for a in reports}
            tech_a = scores_map.get("technical", {})
            fund_a = scores_map.get("fundamental", {})
            macro_a = scores_map.get("macro", {})
            sent_a = scores_map.get("sentiment", {})
            fields.append({
                "name": "Analystes",
                "value": (
                    f"📊 Tech: **{tech_a.get('score', 0):+.1f}** | "
                    f"📈 Fond: **{fund_a.get('score', 0):+.1f}** | "
                    f"🌍 Macro: **{macro_a.get('score', 0):+.1f}** | "
                    f"💬 Sent: **{sent_a.get('score', 0):+.1f}**"
                ),
                "inline": False,
            })

        # Fundamentals row
        for a in reports:
            if a.get("agent_name") == "fundamental" and a.get("metrics"):
                m = a["metrics"]
                parts = []
                if m.get("forward_pe"): parts.append(f"P/E {m['forward_pe']:.0f}")
                if m.get("revenue_growth") is not None: parts.append(f"CA {m['revenue_growth']*100:+.0f}%")
                if m.get("profit_margin") is not None: parts.append(f"Marge {m['profit_margin']*100:.0f}%")
                if m.get("analyst_upside") is not None: parts.append(f"Cible {m['analyst_upside']:+.0f}%")
                if parts:
                    fields.append({"name": "📈 Fondamentaux", "value": " | ".join(parts), "inline": False})

        # Technicals + Filters row
        vals = s.get("values", {})
        filters = s.get("filters", {})
        tech_parts = []
        if vals.get("rsi_14") is not None: tech_parts.append(f"RSI {vals['rsi_14']:.0f}")
        if vals.get("trend_5d") is not None: tech_parts.append(f"5j {vals['trend_5d']:+.1f}%")
        if vals.get("atr_relative") is not None: tech_parts.append(f"Vol {vals['atr_relative']:.1f}%")
        if filters:
            filter_str = " ".join("✅" if v else "❌" for v in filters.values())
            tech_parts.append(filter_str)
        if tech_parts:
            fields.append({"name": "📊 Technique", "value": " | ".join(tech_parts), "inline": False})

        # Debate (if available)
        if db and db.get("key_factor"):
            fields.append({
                "name": f"⚖️ Débat (🐂{db.get('bull_strength', 0)}% vs 🐻{db.get('bear_strength', 0)}%)",
                "value": db["key_factor"][:120],
                "inline": False,
            })

        # LLM summary
        summary = l.get("summary", "")
        if summary:
            fields.append({"name": "💡 Synthèse", "value": summary[:200], "inline": False})

        embeds.append({
            "title": title,
            "description": desc,
            "color": color,
            "fields": fields[:8],
        })

    if not embeds:
        return

    # Discord max 10 embeds per message
    for i in range(0, len(embeds), 10):
        batch = embeds[i:i + 10]
        batch[-1]["timestamp"] = datetime.utcnow().isoformat()
        batch[-1]["footer"] = {
            "text": f"Trading Agent v2 | Scan {market} | {len(valid)} tickers classés par score",
        }
        await send_discord_embed(batch)


async def alert_daily_summary(summary: str) -> None:
    """Send end-of-day summary to Telegram and Discord."""
    await send_telegram(f"📊 <b>RESUME JOURNALIER</b>\n\n{summary}")

    embed = {
        "title": "📊 Résumé Journalier",
        "description": summary[:4096],
        "color": COLOR_INFO,
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {"text": "Trading Agent | Résumé fin de journée"},
    }
    await send_discord_embed([embed])
