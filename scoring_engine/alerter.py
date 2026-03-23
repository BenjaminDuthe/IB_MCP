"""Alert dispatcher: Telegram + Discord webhooks."""

import logging

import httpx

from scoring_engine.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DISCORD_WEBHOOK_URL

logger = logging.getLogger(__name__)

_client = httpx.AsyncClient(timeout=15.0)


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
    except Exception as e:
        logger.error("Telegram error: %s", e)
        return False


async def send_discord(message: str) -> bool:
    if not DISCORD_WEBHOOK_URL:
        return False
    try:
        resp = await _client.post(DISCORD_WEBHOOK_URL, json={"content": message})
        return resp.status_code in (200, 204)
    except Exception as e:
        logger.error("Discord error: %s", e)
        return False


async def alert_signal(ticker: str, score: int, price: float, verdict: str, confidence: int, summary: str) -> None:
    """Send signal alert to Telegram and Discord."""
    emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚠️"}.get(verdict, "❓")

    tg_msg = (
        f"{emoji} <b>SIGNAL {verdict}</b> — {ticker}\n\n"
        f"  Score: <b>{score}/5</b> | Confiance: {confidence}%\n"
        f"  Prix: ${price:.2f}\n"
        f"  {summary}"
    )
    await send_telegram(tg_msg)

    discord_msg = (
        f"{emoji} **SIGNAL {verdict}** — {ticker}\n"
        f"Score: **{score}/5** | Confiance: {confidence}%\n"
        f"Prix: ${price:.2f}\n"
        f"{summary}"
    )
    await send_discord(discord_msg)


async def alert_daily_summary(summary: str) -> None:
    """Send end-of-day summary."""
    await send_telegram(f"📊 <b>RESUME JOURNALIER</b>\n\n{summary}")
    await send_discord(f"📊 **RESUME JOURNALIER**\n\n{summary}")
