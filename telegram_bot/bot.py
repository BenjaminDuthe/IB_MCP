import os
import json
import html as html_mod
import logging
import asyncio
import aiosqlite
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from telegram_bot.db import (
    DB_PATH,
    init_db,
    insert_trade_signal,
    update_signal_status,
    insert_trade_history,
    get_trade_history,
    get_system_state,
    set_system_state,
    get_pending_signals,
    get_performance_stats,
    get_pending_orders,
    update_trade_fill,
    add_watchlist_ticker,
    remove_watchlist_ticker,
    get_watchlist,
    update_watchlist_price,
    update_watchlist_alert,
    get_daily_order_count,
    get_daily_pnl,
)
from telegram_bot.mcp_clients import MCPClientManager
from telegram_bot.orchestrator import Orchestrator
from telegram_bot.safety_guards import (
    check_safety,
    format_safety_result,
    MAX_ORDER_VALUE_USD,
    MAX_DAILY_ORDERS,
    MAX_DAILY_LOSS_USD,
    MAX_POSITION_PCT,
)
from telegram_bot.models import TradeSignal, TradeAction

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Environment
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
IB_ACCOUNT_ID = os.environ.get("IB_ACCOUNT_ID", "")
PORTFOLIO_SCAN_INTERVAL = int(os.environ.get("PORTFOLIO_SCAN_INTERVAL_MINUTES", "60"))
MARKET_SCAN_INTERVAL = int(os.environ.get("MARKET_SCAN_INTERVAL_MINUTES", "30"))
SIGNAL_EXPIRY_MINUTES = int(os.environ.get("SIGNAL_EXPIRY_MINUTES", "30"))

# Global state
mcp_manager = MCPClientManager()
orchestrator: Optional[Orchestrator] = None
scheduler = AsyncIOScheduler()

# Pending signals awaiting user decision: {signal_id: TradeSignal}
pending_signals: dict[int, TradeSignal] = {}

# Stored reference to the Application for scheduled tasks
_application: Application = None

# Session monitoring state
_ib_session_state = "unknown"   # unknown | healthy | recovering | notified
_ib_recovery_attempts = 0
_IB_MAX_RECOVERY = 3

# US market holidays (static list 2025-2026)
US_MARKET_HOLIDAYS = {
    # 2025
    "2025-01-01", "2025-01-20", "2025-02-17", "2025-04-18",
    "2025-05-26", "2025-06-19", "2025-07-04", "2025-09-01",
    "2025-11-27", "2025-12-25",
    # 2026
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03",
    "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07",
    "2026-11-26", "2026-12-25",
}

ET = ZoneInfo("America/New_York")


class _BotContext:
    """Minimal wrapper to pass bot to helpers from scheduled tasks."""
    def __init__(self, bot):
        self.bot = bot


IDEAS_PROMPT = (
    "Tu dois me proposer exactement 3 idees d'achat d'actions DIVERSIFIEES. "
    "REGLE ABSOLUE : chaque action doit etre dans un SECTEUR DIFFERENT. "
    "Varie les secteurs a chaque appel parmi : technologie, defense/aerospatial, pharmacie/biotech, "
    "energie, finance/banque, consommation, industrie, semi-conducteurs, cybersecurite, "
    "intelligence artificielle, luxe, automobile, immobilier, telecoms, mining/matieres premieres.\n\n"
    "Pour chaque action :\n"
    "1. Recupere le cours actuel et les fondamentaux\n"
    "2. Verifie le sentiment social\n"
    "3. Regarde les actualites recentes\n"
    "4. Verifie les recommandations analystes\n\n"
    "Pour chaque idee, presente :\n"
    "- Le ticker et le nom de l'entreprise\n"
    "- Le secteur\n"
    "- Le prix actuel\n"
    "- POURQUOI c'est interessant en ce moment (1-2 phrases simples)\n"
    "- Un prix d'entree suggere et un stop-loss\n"
    "- Un VERDICT CLAIR : 🟢 ACHETER si ca vaut vraiment le coup maintenant, "
    "ou ⚠️ ATTENDRE si le timing n'est pas ideal. Explique en 1 phrase.\n\n"
    "Termine par un classement : quelle est la MEILLEURE des 3 et pourquoi.\n"
    "Genere un trade_signal pour CHACUNE des 3 actions proposees."
)


def authorized(func):
    """Decorator to restrict commands to the authorized chat ID."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        logger.info(f"Incoming message from chat_id={chat_id} (authorized={TELEGRAM_CHAT_ID!r})")
        if TELEGRAM_CHAT_ID and str(chat_id) != TELEGRAM_CHAT_ID:
            logger.warning(f"Unauthorized access from chat_id={chat_id}")
            await update.message.reply_text("Unauthorized.")
            return
        return await func(update, context)
    return wrapper


# ============================================
# A3: US Market Hours Check
# ============================================

def is_us_market_open() -> tuple[bool, str]:
    """Check if the US stock market is currently open.
    Returns (is_open, reason_if_closed).
    """
    now_et = datetime.now(ET)
    date_str = now_et.strftime("%Y-%m-%d")

    # Weekend
    if now_et.weekday() >= 5:
        day_name = "samedi" if now_et.weekday() == 5 else "dimanche"
        return False, f"Marche ferme ({day_name})"

    # Holiday
    if date_str in US_MARKET_HOLIDAYS:
        return False, "Marche ferme (jour ferie US)"

    # Hours: 9:30 - 16:00 ET
    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
    if now_et < market_open:
        return False, f"Pre-market (ouverture a 9:30 ET, il est {now_et.strftime('%H:%M')} ET)"
    if now_et >= market_close:
        return False, f"After-hours (fermeture a 16:00 ET, il est {now_et.strftime('%H:%M')} ET)"

    return True, ""


def _get_next_market_open(now_et: datetime) -> str:
    """Retourne la prochaine ouverture du marche en format lisible."""
    candidate = now_et.date()

    # Si apres 16h ou weekend, avancer
    if now_et.hour >= 16 or now_et.weekday() >= 5:
        candidate += timedelta(days=1)

    # Skip weekends
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)

    # Skip holidays
    while candidate.strftime("%Y-%m-%d") in US_MARKET_HOLIDAYS:
        candidate += timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)

    # Format: "Lundi 10 fev a 9:30 ET"
    jours = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    mois = ["jan", "fev", "mar", "avr", "mai", "juin", "juil", "aout", "sep", "oct", "nov", "dec"]
    return f"{jours[candidate.weekday()]} {candidate.day} {mois[candidate.month-1]} a 9:30 ET"


# ============================================
# Helper: Parse MCP result
# ============================================

def _parse_mcp_result(result) -> dict:
    """Extract data from MCP tool result wrapper {content: [{text: "..."}]}."""
    if isinstance(result, dict):
        # Direct dict result
        content = result.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    try:
                        return json.loads(item["text"])
                    except (json.JSONDecodeError, TypeError):
                        return {"raw": item["text"]}
        return result
    if isinstance(result, str):
        try:
            return json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return {"raw": result}
    return {"raw": str(result)}


def _escape_html(text: str) -> str:
    """Escape HTML special chars in user/API text to prevent formatting issues."""
    return html_mod.escape(str(text))


# ============================================
# A1: Reload pending signals from DB
# ============================================

async def _reload_pending_signals():
    """Reload pending signals from DB after restart, repopulate pending_signals dict."""
    rows = await get_pending_signals()
    count = 0
    for row in rows:
        signal_id = row["id"]
        signal = TradeSignal(
            ticker=row["ticker"],
            action=TradeAction(row["action"]),
            quantity=row.get("quantity"),
            order_type=row.get("order_type"),
            price=row.get("price"),
            confidence=row.get("confidence"),
            reason=row.get("reason"),
            stop_loss=row.get("stop_loss"),
            take_profit=row.get("take_profit"),
        )
        pending_signals[signal_id] = signal
        count += 1
    if count:
        logger.info(f"Reloaded {count} pending signals from DB")


# ============================================
# Telegram Command Handlers
# ============================================

@authorized
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message and help."""
    text = (
        "🤖 Assistant Trading IB\n\n"
        "📋 Commandes disponibles :\n\n"
        "📊 /analyze <ticker> - Analyse complete (donnees + sentiment + actu)\n"
        "💼 /portfolio - Positions actuelles et P&L\n"
        "🌍 /market - Vue d'ensemble du marche\n"
        "💬 /sentiment <ticker> - Sentiment des reseaux sociaux\n"
        "📰 /news <ticker> - Actualites recentes\n"
        "📜 /history - Historique des trades\n"
        "⚙️ /limits - Garde-fous actifs\n"
        "🛑 /stop - ARRET D'URGENCE (bloque toute execution)\n"
        "▶️ /resume - Reactiver le trading\n"
        "💡 /ideas - 3 idees d'achat diversifiees (tous secteurs)\n"
        "🔧 /status - Sante des services\n"
        "📤 /close <ticker> - Fermer une position\n"
        "📊 /performance - Statistiques de trading\n"
        "👁 /watch <ticker> - Ajouter a la watchlist\n"
        "🚫 /unwatch <ticker> - Retirer de la watchlist\n"
        "📋 /watchlist - Voir watchlist + prix actuels\n"
        "🔥 /trending - Tickers tendance (StockTwits/Reddit)\n"
        "📅 /earnings - Earnings a venir cette semaine\n"
        "🔐 /session - Verifier/reparer la session IB\n"
    )
    await update.message.reply_text(text)


@authorized
async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Full analysis of a ticker via Claude + all MCP tools."""
    if not context.args:
        await update.message.reply_text("Usage: /analyze <TICKER>")
        return

    ticker = context.args[0].upper()
    await update.message.reply_text(f"🔍 Analyse de {ticker} en cours... (ca peut prendre 1-2 min)")

    prompt = (
        f"Perform a comprehensive analysis of {ticker}. "
        f"1. Get current price and fundamentals "
        f"2. Check social sentiment (Reddit, StockTwits) "
        f"3. Get recent news "
        f"4. Check analyst recommendations "
        f"5. Based on all data, provide your analysis and recommendation. "
        f"If you see a clear trade opportunity, generate a trade signal."
    )

    try:
        response_text, signals = await orchestrator.process_message(
            prompt, ticker=ticker, trigger_type="analyze"
        )
    except Exception as e:
        logger.error(f"Analyze error: {e}")
        await update.message.reply_text(f"Error: {e}")
        return

    # Send analysis (split if too long for Telegram's 4096 char limit)
    await _send_long_message(update.effective_chat.id, response_text, context)

    # Process any trade signals
    for signal in signals:
        await _process_trade_signal(update.effective_chat.id, signal, context)


@authorized
async def cmd_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current portfolio via IB MCP."""
    await update.message.reply_text("💼 Recuperation du portfolio...")

    try:
        response_text, _ = await orchestrator.process_message(
            "Show my current portfolio positions, P&L, and account summary. "
            "Use the IB portfolio tools to get this information.",
            trigger_type="portfolio",
        )
    except Exception as e:
        logger.error(f"Portfolio error: {e}")
        await update.message.reply_text(f"Error: {e}")
        return
    await _send_long_message(update.effective_chat.id, response_text, context)


@authorized
async def cmd_market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Market overview."""
    await update.message.reply_text("🌍 Vue du marche en cours...")

    try:
        response_text, _ = await orchestrator.process_message(
            "Give me a market overview: major indices (S&P 500, Nasdaq, Dow, Russell 2000, VIX) "
            "and sector performance. Highlight any significant moves.",
            trigger_type="market",
        )
    except Exception as e:
        logger.error(f"Market error: {e}")
        await update.message.reply_text(f"Error: {e}")
        return
    await _send_long_message(update.effective_chat.id, response_text, context)


@authorized
async def cmd_ideas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Propose 3 diversified buy ideas across different sectors."""
    await update.message.reply_text("🔍 Analyse des marches en cours... (ca peut prendre 1-2 min)")

    try:
        response_text, signals = await orchestrator.process_message(
            IDEAS_PROMPT, trigger_type="ideas"
        )
    except Exception as e:
        logger.error(f"Ideas error: {e}")
        await update.message.reply_text(f"Erreur: {e}")
        return

    chat_id = update.effective_chat.id
    await _send_long_message(chat_id, response_text, context)

    if signals:
        # Send a compact recap of all ideas
        emoji_nums = ["1️⃣", "2️⃣", "3️⃣"]
        recap_lines = ["\n💡 <b>IDEES D'ACHAT</b>\n"]
        for i, s in enumerate(signals):
            action_fr = {"BUY": "ACHAT", "SELL": "VENTE"}.get(s.action.value, s.action.value)
            conf = f"{s.confidence:.0f}%" if s.confidence else "?"
            num = emoji_nums[i] if i < len(emoji_nums) else f"{i+1}."
            recap_lines.append(f"{num} {_escape_html(s.ticker)} - {action_fr} @ ${s.price or 0:.2f} - Confiance {conf}")
        recap_lines.append("\nApprouve ou refuse chaque idee ci-dessous 👇")
        await context.bot.send_message(chat_id=chat_id, text="\n".join(recap_lines), parse_mode="HTML")

        # Send each signal individually with approve/reject buttons
        for signal in signals:
            await _process_trade_signal(chat_id, signal, context)


@authorized
async def cmd_sentiment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sentiment analysis for a ticker."""
    if not context.args:
        await update.message.reply_text("Usage: /sentiment <TICKER>")
        return

    ticker = context.args[0].upper()
    await update.message.reply_text(f"💬 Analyse du sentiment pour {ticker}...")

    try:
        response_text, _ = await orchestrator.process_message(
            f"Get the social sentiment for {ticker} from Reddit and StockTwits. "
            f"Provide a summary of the sentiment, mention counts, and notable posts.",
            ticker=ticker,
            trigger_type="sentiment",
        )
    except Exception as e:
        logger.error(f"Sentiment error: {e}")
        await update.message.reply_text(f"Error: {e}")
        return
    await _send_long_message(update.effective_chat.id, response_text, context)


@authorized
async def cmd_news(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Recent news for a ticker."""
    if not context.args:
        await update.message.reply_text("Usage: /news <TICKER>")
        return

    ticker = context.args[0].upper()
    await update.message.reply_text(f"📰 Actualites pour {ticker}...")

    try:
        response_text, _ = await orchestrator.process_message(
            f"Get recent news for {ticker}. Summarize the most important articles "
            f"and their potential impact on the stock.",
            ticker=ticker,
            trigger_type="news",
        )
    except Exception as e:
        logger.error(f"News error: {e}")
        await update.message.reply_text(f"Error: {e}")
        return
    await _send_long_message(update.effective_chat.id, response_text, context)


@authorized
async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show recent trade history."""
    trades = await get_trade_history(limit=10)
    if not trades:
        await update.message.reply_text("Aucun historique de trades.")
        return

    lines = ["📜 Trades recents :\n"]
    for t in trades:
        pnl_str = f" P&L: ${t.get('pnl', 0):.2f}" if t.get("pnl") else ""
        lines.append(
            f"  {t['action']} {t['quantity']} {t['ticker']} "
            f"@ ${t.get('price', 0):.2f} [{t['status']}]{pnl_str}"
        )

    await update.message.reply_text("\n".join(lines))


@authorized
async def cmd_limits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current safety guard settings."""
    daily_orders = await get_daily_order_count()
    daily_pnl = await get_daily_pnl()
    kill_switch = await get_system_state("kill_switch")

    text = (
        "⚙️ Garde-fous :\n\n"
        f"  🛑 Arret d'urgence : {'ACTIF' if kill_switch == 'active' else 'DESACTIVE'}\n"
        f"  💰 Valeur max par ordre : ${MAX_ORDER_VALUE_USD:,.0f}\n"
        f"  📊 Ordres du jour : {daily_orders}/{MAX_DAILY_ORDERS}\n"
        f"  📉 P&L du jour : ${daily_pnl:,.0f} (limite : -${MAX_DAILY_LOSS_USD:,.0f})\n"
        f"  📐 Position max : {MAX_POSITION_PCT}%\n"
    )
    await update.message.reply_text(text)


@authorized
async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Activate kill switch - block all order execution."""
    await set_system_state("kill_switch", "active")
    await update.message.reply_text(
        "🛑 ARRET D'URGENCE ACTIVE\n"
        "Toute execution d'ordres est bloquee.\n"
        "Utilise /resume pour reactiver le trading."
    )


@authorized
async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deactivate kill switch - resume trading."""
    await set_system_state("kill_switch", "inactive")
    await update.message.reply_text("▶️ Trading REACTIVE. Arret d'urgence desactive.")


@authorized
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check health of all services."""
    statuses = mcp_manager.get_server_status()
    lines = ["🔧 Etat des services :\n"]
    for name, info in statuses.items():
        icon = "🟢" if info["connected"] else "🔴"
        lines.append(f"  {icon} {name} : {info['tools_count']} outils")

    kill_switch = await get_system_state("kill_switch")
    lines.append(f"\n  🛑 Arret d'urgence : {'ACTIF' if kill_switch == 'active' else 'DESACTIVE'}")

    market_open, market_reason = is_us_market_open()
    market_icon = "🟢" if market_open else "🔴"
    lines.append(f"  {market_icon} Marche US : {'OUVERT' if market_open else market_reason}")

    await update.message.reply_text("\n".join(lines))


# ============================================
# Session monitoring & recovery
# ============================================

@authorized
async def cmd_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check and repair IB session status."""
    global _ib_session_state, _ib_recovery_attempts

    await update.message.reply_text("🔐 Verification de la session IB...")

    try:
        result = await mcp_manager.call_tool("ib_get_auth_status", {})
        data = _parse_mcp_result(result)
    except Exception as e:
        await update.message.reply_text(
            f"🔴 Impossible de contacter le MCP server IB\n"
            f"Erreur : {e}"
        )
        return

    connected = data.get("connected", False)
    authenticated = data.get("authenticated", False)

    if connected and authenticated:
        _ib_session_state = "healthy"
        _ib_recovery_attempts = 0
        await update.message.reply_text(
            f"🟢 Session IB OK\n\n"
            f"  Connected : {connected}\n"
            f"  Authenticated : {authenticated}\n"
            f"  Etat interne : {_ib_session_state}"
        )
        return

    if connected and not authenticated:
        await update.message.reply_text(
            f"🟡 Session expiree (connected={connected}, authenticated={authenticated})\n"
            f"Tentative de recovery en cours..."
        )
        # Reset counter to allow manual retry
        _ib_recovery_attempts = 0
        _ib_session_state = "recovering"

        try:
            await mcp_manager.call_tool("ib_ssodh_init", {})
            await asyncio.sleep(2)
            await mcp_manager.call_tool("ib_reauthenticate", {})
            await asyncio.sleep(2)
            # Re-check
            result2 = await mcp_manager.call_tool("ib_get_auth_status", {})
            data2 = _parse_mcp_result(result2)
            if data2.get("authenticated", False):
                _ib_session_state = "healthy"
                await update.message.reply_text("🟢 Session retablie avec succes !")
            else:
                _ib_session_state = "notified"
                await update.message.reply_text(
                    "🔴 Recovery echouee. La session necessite un login manuel.\n"
                    "Connectez-vous via https://<gateway>:5000"
                )
        except Exception as e:
            _ib_session_state = "notified"
            await update.message.reply_text(
                f"🔴 Erreur pendant la recovery : {e}\n"
                f"Connectez-vous manuellement via le navigateur."
            )
        return

    # Not connected at all
    _ib_session_state = "notified"
    await update.message.reply_text(
        f"🔴 Connexion backend perdue (connected={connected})\n\n"
        f"Le gateway IB n'est plus joignable.\n"
        f"Actions :\n"
        f"1. Verifier que le container gateway est running\n"
        f"2. Se reconnecter via https://<gateway>:5000"
    )


# ============================================
# A4: /close command
# ============================================

@authorized
async def cmd_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Close an existing position."""
    if not context.args:
        await update.message.reply_text("Usage: /close <TICKER>")
        return

    ticker = context.args[0].upper()
    await update.message.reply_text(f"📤 Recherche de la position {ticker} pour cloture...")

    try:
        response_text, signals = await orchestrator.process_message(
            f"Cherche ma position en {ticker} dans le portfolio. "
            f"Si j'ai une position, genere un trade_signal SELL pour la quantite totale, order_type=MKT. "
            f"Si je n'ai pas de position en {ticker}, dis-le moi.",
            ticker=ticker,
            trigger_type="close",
        )
    except Exception as e:
        logger.error(f"Close error: {e}")
        await update.message.reply_text(f"Erreur: {e}")
        return

    chat_id = update.effective_chat.id
    await _send_long_message(chat_id, response_text, context)

    # Force all signals to SELL
    for signal in signals:
        signal.action = TradeAction.SELL
        await _process_trade_signal(chat_id, signal, context)


# ============================================
# B1: /performance command
# ============================================

@authorized
async def cmd_performance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show trading performance statistics."""
    stats = await get_performance_stats()

    sig = stats["signals"]
    tr = stats["trades"]
    tok = stats["tokens"]

    # Signal breakdown
    sig_lines = []
    for status, count in sorted(sig.items()):
        sig_lines.append(f"  {status}: {count}")
    sig_text = "\n".join(sig_lines) if sig_lines else "  Aucun signal"

    # Win rate
    trades_with_pnl = tr["winners"] + tr["losers"]
    win_rate = f"{tr['winners'] / trades_with_pnl * 100:.1f}%" if trades_with_pnl > 0 else "N/A"

    # Best/worst
    best_str = f"{tr['best_trade']['ticker']} (+${tr['best_trade']['pnl']:.2f})" if tr["best_trade"] else "N/A"
    worst_str = f"{tr['worst_trade']['ticker']} (${tr['worst_trade']['pnl']:.2f})" if tr["worst_trade"] else "N/A"

    # Avg PnL
    avg_str = f"${tr['avg_pnl']:.2f}" if tr["avg_pnl"] is not None else "N/A"

    text = (
        "📊 PERFORMANCE\n\n"
        f"📋 Signaux :\n{sig_text}\n\n"
        f"📈 Trades ({tr['total']} total) :\n"
        f"  Win rate : {win_rate} ({tr['winners']}W / {tr['losers']}L)\n"
        f"  P&L cumule : ${tr['cumulative_pnl']:.2f}\n"
        f"  P&L moyen : {avg_str}\n"
        f"  Meilleur : {best_str}\n"
        f"  Pire : {worst_str}\n"
    )

    if tr["null_pnl_count"] > 0:
        text += f"  ⚠️ {tr['null_pnl_count']} trades sans P&L renseigne\n"

    text += (
        f"\n🤖 Tokens utilises :\n"
        f"  Analyses : {tok['analysis_count']}\n"
        f"  Input : {tok['total_tokens_input']:,}\n"
        f"  Output : {tok['total_tokens_output']:,}\n"
    )

    await update.message.reply_text(text)


# ============================================
# C1: /watch, /unwatch, /watchlist commands
# ============================================

@authorized
async def cmd_watch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a ticker to the watchlist."""
    if not context.args:
        await update.message.reply_text("Usage: /watch <TICKER>")
        return

    ticker = context.args[0].upper()
    added = await add_watchlist_ticker(ticker)
    if added:
        await update.message.reply_text(f"👁 {ticker} ajoute a la watchlist.")
    else:
        await update.message.reply_text(f"{ticker} est deja dans la watchlist.")


@authorized
async def cmd_unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove a ticker from the watchlist."""
    if not context.args:
        await update.message.reply_text("Usage: /unwatch <TICKER>")
        return

    ticker = context.args[0].upper()
    removed = await remove_watchlist_ticker(ticker)
    if removed:
        await update.message.reply_text(f"🚫 {ticker} retire de la watchlist.")
    else:
        await update.message.reply_text(f"{ticker} n'est pas dans la watchlist.")


@authorized
async def cmd_watchlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show watchlist with current prices."""
    items = await get_watchlist()
    if not items:
        await update.message.reply_text("Watchlist vide. Utilise /watch <TICKER> pour ajouter.")
        return

    await update.message.reply_text("📋 Recuperation des prix...")

    lines = ["📋 WATCHLIST\n"]
    for item in items:
        ticker = item["ticker"]
        price_str = "?"
        try:
            result = await mcp_manager.call_tool(
                "mktdata_get_stock_price", {"ticker": ticker}
            )
            data = _parse_mcp_result(result)
            price = data.get("price") or data.get("last") or data.get("lastPrice")
            if price is not None:
                price_str = f"${float(price):.2f}"
                await update_watchlist_price(ticker, float(price))
        except Exception as e:
            logger.warning(f"Failed to get price for {ticker}: {e}")

        last_price = item.get("last_price")
        change_str = ""
        if last_price and price_str != "?":
            try:
                current = float(price_str.replace("$", ""))
                pct = (current - last_price) / last_price * 100
                arrow = "📈" if pct >= 0 else "📉"
                change_str = f" {arrow} {pct:+.1f}%"
            except (ValueError, ZeroDivisionError):
                pass

        lines.append(f"  {ticker} : {price_str}{change_str}")

    await update.message.reply_text("\n".join(lines))


# ============================================
# C2: /trending and /earnings commands
# ============================================

@authorized
async def cmd_trending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show trending tickers from social media."""
    await update.message.reply_text("🔥 Recherche des tickers tendance...")

    try:
        response_text, signals = await orchestrator.process_message(
            "Recupere les tickers tendance sur StockTwits. "
            "Donne le top 5 avec pour chacun : prix actuel, sentiment, et news recentes. "
            "Utilise sentiment_get_trending_tickers, mktdata_get_stock_price, et news_get_stock_news.",
            trigger_type="trending",
        )
    except Exception as e:
        logger.error(f"Trending error: {e}")
        await update.message.reply_text(f"Erreur: {e}")
        return

    chat_id = update.effective_chat.id
    await _send_long_message(chat_id, response_text, context)

    for signal in signals:
        await _process_trade_signal(chat_id, signal, context)


@authorized
async def cmd_earnings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show upcoming earnings this week."""
    await update.message.reply_text("📅 Recherche du calendrier des earnings...")

    try:
        response_text, signals = await orchestrator.process_message(
            "Calendrier des earnings de la semaine. Top 10 des entreprises les plus suivies. "
            "Pour chacune : date/heure du rapport, EPS estime, prix actuel, et sentiment. "
            "Utilise news_get_earnings_calendar, mktdata_get_stock_price, et sentiment_get_combined_sentiment.",
            trigger_type="earnings",
        )
    except Exception as e:
        logger.error(f"Earnings error: {e}")
        await update.message.reply_text(f"Erreur: {e}")
        return

    chat_id = update.effective_chat.id
    await _send_long_message(chat_id, response_text, context)

    for signal in signals:
        await _process_trade_signal(chat_id, signal, context)


# ============================================
# Trade Signal Processing & Validation Flow
# ============================================

async def _process_trade_signal(
    chat_id: int | str,
    signal: TradeSignal,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Process a trade signal: safety check -> notification -> await user decision."""
    # Run safety checks
    safety_result = await check_safety(signal)

    if not safety_result.passed:
        # Signal blocked by safety guards
        signal_id = await insert_trade_signal(
            ticker=signal.ticker,
            action=signal.action.value,
            quantity=signal.quantity,
            order_type=signal.order_type,
            price=signal.price,
            confidence=signal.confidence,
            reason=signal.reason,
            status="safety_blocked",
            safety_check_result=json.dumps(safety_result.checks),
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"🚫 <b>SIGNAL BLOQUE</b>\n\n"
                f"{_escape_html(signal.action.value)} {signal.quantity} {_escape_html(signal.ticker)} "
                f"@ ${signal.price or 0:.2f} {_escape_html(signal.order_type or 'MKT')}\n\n"
                f"Raison : {_escape_html(safety_result.blocked_reason)}\n\n"
                f"Controles :\n{_escape_html(format_safety_result(safety_result))}"
            ),
            parse_mode="HTML",
        )
        return

    # Signal passed safety checks - save and send notification
    signal_id = await insert_trade_signal(
        ticker=signal.ticker,
        action=signal.action.value,
        quantity=signal.quantity,
        order_type=signal.order_type,
        price=signal.price,
        confidence=signal.confidence,
        reason=signal.reason,
        status="pending",
        safety_check_result=json.dumps(safety_result.checks),
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit,
    )

    pending_signals[signal_id] = signal

    # Build inline keyboard for user decision
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ APPROUVER", callback_data=f"approve_{signal_id}"),
            InlineKeyboardButton("❌ REFUSER", callback_data=f"reject_{signal_id}"),
        ],
    ])

    confidence_str = f"{signal.confidence:.0f}%" if signal.confidence else "N/A"
    stop_loss_str = f"${signal.stop_loss:.2f}" if signal.stop_loss else "Aucun"
    take_profit_str = f"${signal.take_profit:.2f}" if signal.take_profit else "Aucun"

    action_fr = {"BUY": "ACHAT", "SELL": "VENTE", "HOLD": "CONSERVER"}.get(signal.action.value, signal.action.value)

    text = (
        f"📊 <b>SIGNAL #{signal_id}</b>\n\n"
        f"  {_escape_html(action_fr)} {signal.quantity} {_escape_html(signal.ticker)} "
        f"@ ${signal.price or 0:.2f} {_escape_html(signal.order_type or 'MKT')}\n\n"
        f"  Confiance : {confidence_str}\n"
        f"  Stop Loss : {stop_loss_str}\n"
        f"  Objectif : {take_profit_str}\n\n"
        f"  Raison : {_escape_html(signal.reason or 'N/A')}\n\n"
        f"Controles :\n{_escape_html(format_safety_result(safety_result))}"
    )

    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )

    # Update signal with telegram message id
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE trade_signals SET telegram_message_id=? WHERE id=?",
            (msg.message_id, signal_id),
        )
        await db.commit()


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard button presses for trade approval/rejection."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.startswith("approve_"):
        signal_id = int(data.split("_")[1])
        await _handle_approve_step1(query, signal_id, context)
    elif data.startswith("confirm_exec_"):
        signal_id = int(data.split("_")[2])
        await _handle_confirm_execute(query, signal_id, context)
    elif data.startswith("cancel_exec_"):
        signal_id = int(data.split("_")[2])
        await _handle_cancel_execute(query, signal_id, context)
    elif data.startswith("reject_"):
        signal_id = int(data.split("_")[1])
        await _handle_reject(query, signal_id, context)
    elif data.startswith("force_exec_"):
        signal_id = int(data.split("_")[2])
        await _execute_order(query, signal_id, pending_signals.get(signal_id), context)


async def _handle_approve_step1(query, signal_id: int, context):
    """First approval step - show confirmation dialog."""
    signal = pending_signals.get(signal_id)
    if not signal:
        await query.edit_message_text("Signal expire ou introuvable.")
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🟢 OUI, EXECUTER", callback_data=f"confirm_exec_{signal_id}"
            ),
            InlineKeyboardButton(
                "🔴 ANNULER", callback_data=f"cancel_exec_{signal_id}"
            ),
        ],
    ])

    action_fr = {"BUY": "ACHAT", "SELL": "VENTE", "HOLD": "CONSERVER"}.get(signal.action.value, signal.action.value)

    await query.edit_message_text(
        f"⚠️ <b>CONFIRMER L'EXECUTION ?</b>\n\n"
        f"  {_escape_html(action_fr)} {signal.quantity} {_escape_html(signal.ticker)} "
        f"@ ${signal.price or 0:.2f} {_escape_html(signal.order_type or 'MKT')}\n\n"
        f"Cela va passer un ordre reel sur Interactive Brokers.",
        reply_markup=keyboard,
        parse_mode="HTML",
    )


async def _handle_confirm_execute(query, signal_id: int, context):
    """Second confirmation - check market hours, then execute or warn."""
    signal = pending_signals.get(signal_id)
    if not signal:
        await query.edit_message_text("Signal expire ou introuvable.")
        return

    # A3: Check market hours before execution
    market_open, market_reason = is_us_market_open()
    if not market_open:
        now_et = datetime.now(ET)
        date_str = now_et.strftime("%Y-%m-%d")

        # Determiner le type de fermeture pour adapter le message
        if now_et.weekday() >= 5 or date_str in US_MARKET_HOLIDAYS:
            # Weekend ou ferie -> pas de trading possible
            next_open = _get_next_market_open(now_et)
            msg = (
                f"🔴 <b>MARCHE FERME</b>\n\n"
                f"{_escape_html(market_reason)}\n\n"
                f"⏰ Prochaine ouverture : {next_open}\n\n"
                f"❌ Impossible d'executer maintenant.\n"
                f"Le marche US n'accepte pas d'ordres le weekend/jours feries."
            )
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("OK", callback_data=f"cancel_exec_{signal_id}")
            ]])
        else:
            # Pre/After-market -> trading possible mais risque
            msg = (
                f"🟠 <b>HORS HORAIRES</b>\n\n"
                f"{_escape_html(market_reason)}\n\n"
                f"⚠️ <b>Risques du trading hors marche :</b>\n"
                f"• Liquidite reduite → spreads plus larges\n"
                f"• Prix peut s'ecarter du dernier cours\n"
                f"• Ordre limite recommande (pas market)\n\n"
                f"Executer quand meme ?"
            )
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("⚠️ EXECUTER", callback_data=f"force_exec_{signal_id}"),
                    InlineKeyboardButton("❌ ANNULER", callback_data=f"cancel_exec_{signal_id}"),
                ],
            ])

        await query.edit_message_text(msg, reply_markup=keyboard, parse_mode="HTML")
        return

    await _execute_order(query, signal_id, signal, context)


async def _execute_order(query, signal_id: int, signal: TradeSignal, context):
    """Actually execute the trade via IB MCP."""
    if not signal:
        signal = pending_signals.get(signal_id)
    if not signal:
        await query.edit_message_text("Signal expire ou introuvable.")
        return

    # Pre-check IB session before executing
    try:
        auth_result = await mcp_manager.call_tool("ib_get_auth_status", {})
        auth_data = _parse_mcp_result(auth_result)
        auth_connected = auth_data.get("connected", False)
        auth_authenticated = auth_data.get("authenticated", False)

        if auth_connected and not auth_authenticated:
            # Attempt auto-recovery
            try:
                await mcp_manager.call_tool("ib_ssodh_init", {})
                await asyncio.sleep(2)
                await mcp_manager.call_tool("ib_reauthenticate", {})
                await asyncio.sleep(2)
                recheck = await mcp_manager.call_tool("ib_get_auth_status", {})
                recheck_data = _parse_mcp_result(recheck)
                auth_authenticated = recheck_data.get("authenticated", False)
            except Exception as e:
                logger.warning(f"Pre-check recovery failed: {e}")

            if not auth_authenticated:
                await query.edit_message_text(
                    f"🔴 Session IB expiree - ordre non execute\n\n"
                    f"  {signal.action.value} {signal.quantity} {signal.ticker}\n\n"
                    f"La session brokerage a expire. Utilisez /session pour reparer\n"
                    f"ou connectez-vous manuellement. Le signal reste en attente."
                )
                return

        if not auth_connected:
            await query.edit_message_text(
                f"🔴 Connexion IB perdue - ordre non execute\n\n"
                f"  {signal.action.value} {signal.quantity} {signal.ticker}\n\n"
                f"Le gateway n'est plus connecte. Le signal reste en attente."
            )
            return
    except Exception as e:
        # MCP unreachable — continue best effort
        logger.warning(f"Pre-check session failed (continuing): {e}")

    pending_signals.pop(signal_id, None)
    await update_signal_status(signal_id, "approved", user_decision="approved")

    # Execute via IB MCP
    await query.edit_message_text(
        f"⏳ Execution en cours : {signal.action.value} {signal.quantity} {signal.ticker}..."
    )

    try:
        order_payload = {
            "accountId": IB_ACCOUNT_ID,
            "orders": [{
                "acctId": IB_ACCOUNT_ID,
                "ticker": signal.ticker,
                "side": signal.action.value,
                "orderType": signal.order_type or "LMT",
                "quantity": signal.quantity,
                "price": signal.price,
                "tif": "DAY",
            }],
        }

        # Try preview first
        try:
            preview_result = await mcp_manager.call_tool(
                "ib_preview_order_iserver_account", order_payload
            )
            logger.info(f"Order preview: {preview_result}")
        except Exception as e:
            logger.warning(f"Preview failed (continuing): {e}")

        # Place the order
        order_result = await mcp_manager.call_tool(
            "ib_place_order_iserver_account", order_payload
        )

        # Extract ib_order_id (handle both direct dict and MCP content wrapper)
        ib_order_id = None
        if isinstance(order_result, dict):
            ib_order_id = str(order_result.get("order_id", order_result.get("orderId", "")))
            if not ib_order_id:
                # Try MCP content wrapper
                parsed = _parse_mcp_result(order_result)
                ib_order_id = str(parsed.get("order_id", parsed.get("orderId", "")))

        await insert_trade_history(
            signal_id=signal_id,
            ticker=signal.ticker,
            action=signal.action.value,
            quantity=signal.quantity,
            order_type=signal.order_type or "LMT",
            price=signal.price,
            ib_order_id=ib_order_id or None,
            status="submitted",
        )

        await update_signal_status(signal_id, "executed")

        order_data = _parse_mcp_result(order_result)
        ib_oid = order_data.get("order_id") or order_data.get("orderId") or order_data.get("id", "")
        result_str = f"Order ID: {_escape_html(str(ib_oid))}" if ib_oid else "Ordre soumis"
        if order_data.get("error"):
            result_str = f"Erreur: {_escape_html(str(order_data['error']))}"
            detail = order_data.get("detail", "")
            if detail:
                try:
                    detail_parsed = json.loads(detail) if isinstance(detail, str) and detail.startswith('{') else detail
                    if isinstance(detail_parsed, dict):
                        detail = detail_parsed.get("error", detail)
                except (json.JSONDecodeError, TypeError):
                    pass
                result_str += f"\n{_escape_html(str(detail))}"

        await query.edit_message_text(
            f"✅ <b>ORDRE EXECUTE</b>\n\n"
            f"  {_escape_html(signal.action.value)} {signal.quantity} {_escape_html(signal.ticker)} "
            f"@ ${signal.price or 0:.2f} {_escape_html(signal.order_type or 'MKT')}\n\n"
            f"{result_str}",
            parse_mode="HTML",
        )

    except Exception as e:
        logger.error(f"Order execution failed: {e}")
        await update_signal_status(signal_id, "failed")
        await insert_trade_history(
            signal_id=signal_id,
            ticker=signal.ticker,
            action=signal.action.value,
            quantity=signal.quantity,
            order_type=signal.order_type or "LMT",
            price=signal.price,
            status="failed",
        )
        await query.edit_message_text(
            f"❌ <b>ORDRE ECHOUE</b>\n\n"
            f"  {_escape_html(signal.action.value)} {signal.quantity} {_escape_html(signal.ticker)}\n\n"
            f"Erreur : {_escape_html(str(e))}",
            parse_mode="HTML",
        )


async def _handle_reject(query, signal_id: int, context):
    """Reject a trade signal."""
    pending_signals.pop(signal_id, None)
    await update_signal_status(signal_id, "rejected", user_decision="rejected")
    await query.edit_message_text(f"Signal #{signal_id} REFUSE.")


async def _handle_cancel_execute(query, signal_id: int, context):
    """Cancel execution after first approval."""
    pending_signals.pop(signal_id, None)
    await update_signal_status(signal_id, "rejected", user_decision="cancelled")
    await query.edit_message_text(f"Execution annulee pour le signal #{signal_id}.")


# ============================================
# Scheduled Tasks
# ============================================

async def scheduled_portfolio_scan():
    """Periodic portfolio scan."""
    if not TELEGRAM_CHAT_ID:
        return

    # A3: Skip if market is closed
    market_open, _ = is_us_market_open()
    if not market_open:
        logger.info("Portfolio scan skipped: market closed")
        return

    try:
        response_text, signals = await orchestrator.process_message(
            "Scan my current portfolio. Check for any positions that need attention: "
            "significant P&L changes, approaching stop losses, or risk concentrations. "
            "Only generate a trade signal if action is clearly needed.",
            trigger_type="scheduled_portfolio",
        )
        # Only notify if there's something significant
        if signals or "attention" in response_text.lower() or "alert" in response_text.lower():
            await _application.bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=f"📋 <b>Portfolio Scan</b>\n\n{response_text[:4000]}",
                parse_mode="HTML",
            )
    except Exception as e:
        logger.error(f"Scheduled portfolio scan failed: {e}")


async def scheduled_market_scan():
    """Periodic market scan."""
    if not TELEGRAM_CHAT_ID:
        return

    # A3: Skip if market is closed
    market_open, _ = is_us_market_open()
    if not market_open:
        logger.info("Market scan skipped: market closed")
        return

    try:
        response_text, _ = await orchestrator.process_message(
            "Quick market pulse check: any significant moves in major indices or VIX? "
            "Only report if there's something noteworthy.",
            trigger_type="scheduled_market",
        )
        if any(word in response_text.lower() for word in ["significant", "alert", "unusual", "spike", "crash", "surge"]):
            await _application.bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=f"🚨 <b>Market Alert</b>\n\n{response_text[:4000]}",
                parse_mode="HTML",
            )
    except Exception as e:
        logger.error(f"Scheduled market scan failed: {e}")


async def scheduled_ideas_scan():
    """Automatic buy ideas scan, runs 2x/day during US market hours."""
    if not TELEGRAM_CHAT_ID:
        return

    chat_id = TELEGRAM_CHAT_ID

    try:
        response_text, signals = await orchestrator.process_message(
            IDEAS_PROMPT, trigger_type="scheduled_ideas"
        )
    except Exception as e:
        logger.error(f"Scheduled ideas scan failed: {e}")
        return

    bot_ctx = _BotContext(_application.bot)
    await _send_long_message(chat_id, response_text, bot_ctx)

    if signals:
        emoji_nums = ["1️⃣", "2️⃣", "3️⃣"]
        recap_lines = ["\n💡 <b>IDEES D'ACHAT</b> (scan auto)\n"]
        for i, s in enumerate(signals):
            action_fr = {"BUY": "ACHAT", "SELL": "VENTE"}.get(s.action.value, s.action.value)
            conf = f"{s.confidence:.0f}%" if s.confidence else "?"
            num = emoji_nums[i] if i < len(emoji_nums) else f"{i+1}."
            recap_lines.append(f"{num} {_escape_html(s.ticker)} - {action_fr} @ ${s.price or 0:.2f} - Confiance {conf}")
        recap_lines.append("\nApprouve ou refuse chaque idee ci-dessous 👇")
        await _application.bot.send_message(chat_id=chat_id, text="\n".join(recap_lines), parse_mode="HTML")

        for signal in signals:
            await _process_trade_signal(chat_id, signal, bot_ctx)


# ============================================
# Session Monitor (auto-reconnect)
# ============================================

async def scheduled_session_monitor():
    """Check IB session health every 2 minutes and attempt auto-recovery."""
    global _ib_session_state, _ib_recovery_attempts

    if not TELEGRAM_CHAT_ID or not _application:
        return

    try:
        result = await mcp_manager.call_tool("ib_get_auth_status", {})
        data = _parse_mcp_result(result)
    except Exception as e:
        logger.warning(f"Session monitor: MCP unreachable - {e}")
        _ib_session_state = "unknown"
        return

    connected = data.get("connected", False)
    authenticated = data.get("authenticated", False)
    previous_state = _ib_session_state

    # Case 1: Healthy
    if connected and authenticated:
        if previous_state in ("recovering", "notified"):
            logger.info("Session monitor: session recovered")
            try:
                await _application.bot.send_message(
                    chat_id=TELEGRAM_CHAT_ID,
                    text="🟢 <b>Session IB retablie</b> automatiquement.",
                    parse_mode="HTML",
                )
            except Exception:
                pass
        _ib_session_state = "healthy"
        _ib_recovery_attempts = 0
        return

    # Case 2: Connected but not authenticated → auto-repair
    if connected and not authenticated:
        if _ib_session_state == "notified":
            # Already notified, don't spam — wait for healthy
            return

        _ib_recovery_attempts += 1
        _ib_session_state = "recovering"
        logger.info(f"Session monitor: recovering (attempt {_ib_recovery_attempts}/{_IB_MAX_RECOVERY})")

        if _ib_recovery_attempts > _IB_MAX_RECOVERY:
            _ib_session_state = "notified"
            logger.warning("Session monitor: max recovery attempts reached")
            try:
                await _application.bot.send_message(
                    chat_id=TELEGRAM_CHAT_ID,
                    text=(
                        "🔴 <b>Session IB expiree</b> - recovery auto echouee\n\n"
                        "La session brokerage a expire et les tentatives automatiques "
                        "n'ont pas reussi.\n"
                        "👉 Connectez-vous manuellement via le navigateur gateway\n"
                        "Ou utilisez /session pour retenter."
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass
            return

        # Attempt recovery: ssodh_init + reauthenticate
        try:
            await mcp_manager.call_tool("ib_ssodh_init", {})
            await asyncio.sleep(2)
            await mcp_manager.call_tool("ib_reauthenticate", {})
            logger.info("Session monitor: recovery commands sent, will verify next cycle")
        except Exception as e:
            logger.warning(f"Session monitor: recovery call failed - {e}")
        return

    # Case 3: Not connected at all → notify once
    if not connected:
        if _ib_session_state != "notified":
            _ib_session_state = "notified"
            logger.warning("Session monitor: backend connection lost")
            try:
                await _application.bot.send_message(
                    chat_id=TELEGRAM_CHAT_ID,
                    text=(
                        "🔴 <b>Connexion IB Gateway perdue</b>\n\n"
                        "Le backend n'est plus connecte. Login manuel SSO requis.\n"
                        "👉 Connectez-vous via https://&lt;gateway&gt;:5000\n"
                        "Utilisez /session pour verifier apres reconnexion."
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass
        return


# ============================================
# A2: Signal Expiration
# ============================================

async def scheduled_expire_signals():
    """Expire pending signals older than SIGNAL_EXPIRY_MINUTES."""
    now = datetime.now(timezone.utc)
    rows = await get_pending_signals()

    for row in rows:
        signal_id = row["id"]
        created_str = row["created_at"]
        try:
            # SQLite stores timestamps as strings; parse them
            created_at = datetime.fromisoformat(created_str)
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue

        age_minutes = (now - created_at).total_seconds() / 60
        if age_minutes > SIGNAL_EXPIRY_MINUTES:
            await update_signal_status(signal_id, "expired")
            pending_signals.pop(signal_id, None)
            logger.info(f"Signal #{signal_id} expired (age: {age_minutes:.0f}min)")

            # Try to edit the Telegram message
            telegram_msg_id = row.get("telegram_message_id")
            if telegram_msg_id and _application:
                try:
                    await _application.bot.edit_message_text(
                        chat_id=TELEGRAM_CHAT_ID,
                        message_id=telegram_msg_id,
                        text=f"⏰ Signal #{signal_id} EXPIRE ({row['action']} {row['ticker']})\n"
                             f"Expire apres {SIGNAL_EXPIRY_MINUTES} minutes sans decision.",
                    )
                except Exception as e:
                    logger.warning(f"Could not edit expired signal message: {e}")


# ============================================
# B2: Order Fill Tracking
# ============================================

async def check_order_fills():
    """Check status of submitted orders via IB MCP."""
    orders = await get_pending_orders()
    if not orders:
        return

    for order in orders:
        trade_id = order["id"]
        ib_order_id = order["ib_order_id"]

        try:
            result = await mcp_manager.call_tool(
                "ib_get_order_status", {"orderId": ib_order_id}
            )
            data = _parse_mcp_result(result)

            status = data.get("status", "").lower()
            if status in ("filled", "executed"):
                filled_price = data.get("avgPrice") or data.get("filled_price") or data.get("price")
                commission = data.get("commission")
                pnl = data.get("realizedPnl") or data.get("pnl")
                filled_at = data.get("filledAt") or datetime.now(timezone.utc).isoformat()

                await update_trade_fill(
                    trade_id=trade_id,
                    status="filled",
                    filled_price=float(filled_price) if filled_price else None,
                    filled_at=filled_at,
                    commission=float(commission) if commission else None,
                    pnl=float(pnl) if pnl else None,
                )

                if _application and TELEGRAM_CHAT_ID:
                    price_str = f"@ ${float(filled_price):.2f}" if filled_price else ""
                    pnl_str = f"\nP&amp;L: ${float(pnl):.2f}" if pnl else ""
                    await _application.bot.send_message(
                        chat_id=TELEGRAM_CHAT_ID,
                        text=(
                            f"✅ <b>ORDRE REMPLI</b>\n\n"
                            f"  {_escape_html(order['action'])} {order['quantity']} {_escape_html(order['ticker'])} {price_str}\n"
                            f"  Order ID: {_escape_html(str(ib_order_id))}{pnl_str}"
                        ),
                        parse_mode="HTML",
                    )
                logger.info(f"Order {ib_order_id} filled for {order['ticker']}")

            elif status in ("cancelled", "inactive", "canceled"):
                await update_trade_fill(trade_id=trade_id, status="cancelled")

                if _application and TELEGRAM_CHAT_ID:
                    await _application.bot.send_message(
                        chat_id=TELEGRAM_CHAT_ID,
                        text=(
                            f"🚫 <b>ORDRE ANNULE</b>\n\n"
                            f"  {_escape_html(order['action'])} {order['quantity']} {_escape_html(order['ticker'])}\n"
                            f"  Order ID: {_escape_html(str(ib_order_id))}\n"
                            f"  Statut IB: {_escape_html(status)}"
                        ),
                        parse_mode="HTML",
                    )
                logger.info(f"Order {ib_order_id} cancelled for {order['ticker']}")

        except Exception as e:
            logger.warning(f"Failed to check order {ib_order_id}: {e}")


async def expire_stale_orders():
    """Expire orders that have been submitted for more than 4 hours."""
    orders = await get_pending_orders()
    now = datetime.now(timezone.utc)

    for order in orders:
        try:
            created_at = datetime.fromisoformat(order["created_at"])
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue

        age_hours = (now - created_at).total_seconds() / 3600
        if age_hours > 4:
            await update_trade_fill(trade_id=order["id"], status="expired")
            logger.info(f"Order {order['ib_order_id']} expired (age: {age_hours:.1f}h)")

            if _application and TELEGRAM_CHAT_ID:
                try:
                    await _application.bot.send_message(
                        chat_id=TELEGRAM_CHAT_ID,
                        text=(
                            f"⏰ <b>ORDRE EXPIRE</b>\n\n"
                            f"  {_escape_html(order['action'])} {order['quantity']} {_escape_html(order['ticker'])}\n"
                            f"  Order ID: {_escape_html(str(order['ib_order_id']))}\n"
                            f"  Soumis il y a {age_hours:.1f}h sans remplissage"
                        ),
                        parse_mode="HTML",
                    )
                except Exception as e:
                    logger.warning(f"Could not notify stale order expiry: {e}")


# ============================================
# C1: Watchlist Scan
# ============================================

async def scheduled_watchlist_scan():
    """Scan watchlist for significant price movements."""
    if not TELEGRAM_CHAT_ID or not _application:
        return

    items = await get_watchlist()
    if not items:
        return

    now = datetime.now(timezone.utc)

    for item in items:
        ticker = item["ticker"]
        last_price = item.get("last_price")

        # Check cooldown (2h since last alert)
        last_alert = item.get("last_alert_at")
        if last_alert:
            try:
                alert_at = datetime.fromisoformat(last_alert)
                if alert_at.tzinfo is None:
                    alert_at = alert_at.replace(tzinfo=timezone.utc)
                if (now - alert_at).total_seconds() < 7200:
                    continue
            except (ValueError, TypeError):
                pass

        try:
            result = await mcp_manager.call_tool(
                "mktdata_get_stock_price", {"ticker": ticker}
            )
            data = _parse_mcp_result(result)
            current_price = data.get("price") or data.get("last") or data.get("lastPrice")

            if current_price is None:
                continue

            current_price = float(current_price)
            await update_watchlist_price(ticker, current_price)

            # Alert if movement > 3% from last known price
            if last_price and last_price > 0:
                pct_change = (current_price - last_price) / last_price * 100
                if abs(pct_change) >= 3.0:
                    direction = "📈 HAUSSE" if pct_change > 0 else "📉 BAISSE"
                    await _application.bot.send_message(
                        chat_id=TELEGRAM_CHAT_ID,
                        text=(
                            f"🚨 <b>ALERTE WATCHLIST</b>\n\n"
                            f"  {_escape_html(ticker)} : {direction} {pct_change:+.1f}%\n"
                            f"  ${last_price:.2f} → ${current_price:.2f}"
                        ),
                        parse_mode="HTML",
                    )
                    await update_watchlist_alert(ticker)

        except Exception as e:
            logger.warning(f"Watchlist scan failed for {ticker}: {e}")


# ============================================
# C2: Weekly Digest & Premarket Earnings
# ============================================

async def scheduled_weekly_digest():
    """Monday morning weekly briefing."""
    if not TELEGRAM_CHAT_ID or not _application:
        return

    try:
        response_text, signals = await orchestrator.process_message(
            "Briefing hebdomadaire complet : "
            "1. Earnings importants de la semaine (news_get_earnings_calendar) "
            "2. Tickers tendance (sentiment_get_trending_tickers) "
            "3. Resume des mouvements de la semaine passee "
            "4. Opportunites a surveiller cette semaine "
            "Sois synthetique mais complet.",
            trigger_type="weekly_digest",
        )
    except Exception as e:
        logger.error(f"Weekly digest failed: {e}")
        return

    bot_ctx = _BotContext(_application.bot)
    await _send_long_message(TELEGRAM_CHAT_ID, f"📅 <b>BRIEFING HEBDOMADAIRE</b>\n\n{response_text}", bot_ctx)

    for signal in signals:
        await _process_trade_signal(TELEGRAM_CHAT_ID, signal, bot_ctx)


async def scheduled_premarket_earnings():
    """Pre-market check for today's earnings."""
    if not TELEGRAM_CHAT_ID or not _application:
        return

    try:
        # Get today's earnings via MCP directly
        result = await mcp_manager.call_tool(
            "news_get_earnings_calendar", {}
        )
        data = _parse_mcp_result(result)

        # Cross-reference with watchlist
        watchlist_items = await get_watchlist()
        watchlist_tickers = {item["ticker"] for item in watchlist_items}

        # Parse earnings data
        earnings_today = []
        raw_text = data.get("raw", "")
        if isinstance(data, dict) and "earnings" in data:
            earnings_today = data["earnings"]
        elif raw_text:
            # Let orchestrator format it nicely
            response_text, _ = await orchestrator.process_message(
                f"Voici le calendrier des earnings brut : {str(data)[:2000]}\n\n"
                f"Ma watchlist : {', '.join(watchlist_tickers) if watchlist_tickers else 'vide'}\n\n"
                "Filtre les earnings du jour. Mets en evidence ceux qui sont dans ma watchlist. "
                "Resume en format court.",
                trigger_type="premarket_earnings",
            )
            await _application.bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=f"🌅 <b>EARNINGS DU JOUR</b>\n\n{response_text[:4000]}",
                parse_mode="HTML",
            )
            return

        if not earnings_today:
            return

        # Format notification
        lines = ["🌅 <b>EARNINGS DU JOUR</b>\n"]
        for e in earnings_today[:10]:
            ticker = e.get("ticker", e.get("symbol", "?"))
            in_wl = " 👁" if ticker in watchlist_tickers else ""
            eps = e.get("epsEstimate", "?")
            lines.append(f"  {_escape_html(str(ticker))}{in_wl} - EPS est: {_escape_html(str(eps))}")

        await _application.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text="\n".join(lines),
            parse_mode="HTML",
        )

    except Exception as e:
        logger.error(f"Premarket earnings check failed: {e}")


# ============================================
# Helper
# ============================================

async def _send_long_message(chat_id, text: str, context):
    """Send a long message, splitting into chunks if needed (Telegram limit: 4096 chars)."""
    max_len = 4000
    if len(text) <= max_len:
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        return

    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Find a good split point
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    for chunk in chunks:
        await context.bot.send_message(chat_id=chat_id, text=chunk, parse_mode="HTML")


# ============================================
# Main
# ============================================

async def post_init(application: Application):
    """Initialize MCP connections and database after bot starts."""
    global orchestrator, _application

    logger.info("Initializing database...")
    await init_db()

    logger.info("Discovering MCP tools...")
    await mcp_manager.discover_tools()

    orchestrator = Orchestrator(mcp_manager)
    _application = application

    # A1: Reload pending signals from DB
    await _reload_pending_signals()

    # Start scheduler
    scheduler.add_job(
        scheduled_portfolio_scan,
        "interval",
        minutes=PORTFOLIO_SCAN_INTERVAL,
        id="portfolio_scan",
    )
    scheduler.add_job(
        scheduled_market_scan,
        "interval",
        minutes=MARKET_SCAN_INTERVAL,
        id="market_scan",
    )
    scheduler.add_job(
        scheduled_ideas_scan,
        "cron",
        day_of_week="mon-fri",
        hour="10,14",
        minute=0,
        timezone="America/New_York",
        id="ideas_scan",
    )
    # Session monitor every 2 minutes
    scheduler.add_job(
        scheduled_session_monitor,
        "interval",
        minutes=2,
        id="session_monitor",
    )
    # A2: Signal expiration every 2 minutes
    scheduler.add_job(
        scheduled_expire_signals,
        "interval",
        minutes=2,
        id="expire_signals",
    )
    # B2: Check order fills every 30 seconds
    scheduler.add_job(
        check_order_fills,
        "interval",
        seconds=30,
        id="check_order_fills",
    )
    # B2: Expire stale orders every 15 minutes
    scheduler.add_job(
        expire_stale_orders,
        "interval",
        minutes=15,
        id="expire_stale_orders",
    )
    # C1: Watchlist scan during market hours
    scheduler.add_job(
        scheduled_watchlist_scan,
        "cron",
        day_of_week="mon-fri",
        hour="9-16",
        minute="*/15",
        timezone="America/New_York",
        id="watchlist_scan",
    )
    # C2: Weekly digest Monday 9:00 ET
    scheduler.add_job(
        scheduled_weekly_digest,
        "cron",
        day_of_week="mon",
        hour=9,
        minute=0,
        timezone="America/New_York",
        id="weekly_digest",
    )
    # C2: Premarket earnings check weekdays 8:30 ET
    scheduler.add_job(
        scheduled_premarket_earnings,
        "cron",
        day_of_week="mon-fri",
        hour=8,
        minute=30,
        timezone="America/New_York",
        id="premarket_earnings",
    )
    scheduler.start()

    logger.info("Bot initialized. Scheduler started.")

    # Log status
    status = mcp_manager.get_server_status()
    for name, info in status.items():
        logger.info(f"  {name}: {info['tools_count']} tools, connected={info['connected']}")


def main():
    """Entry point."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Register handlers
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("analyze", cmd_analyze))
    application.add_handler(CommandHandler("portfolio", cmd_portfolio))
    application.add_handler(CommandHandler("market", cmd_market))
    application.add_handler(CommandHandler("ideas", cmd_ideas))
    application.add_handler(CommandHandler("sentiment", cmd_sentiment))
    application.add_handler(CommandHandler("news", cmd_news))
    application.add_handler(CommandHandler("history", cmd_history))
    application.add_handler(CommandHandler("limits", cmd_limits))
    application.add_handler(CommandHandler("stop", cmd_stop))
    application.add_handler(CommandHandler("resume", cmd_resume))
    application.add_handler(CommandHandler("status", cmd_status))
    # A4: /close
    application.add_handler(CommandHandler("close", cmd_close))
    # B1: /performance
    application.add_handler(CommandHandler("performance", cmd_performance))
    # C1: watchlist
    application.add_handler(CommandHandler("watch", cmd_watch))
    application.add_handler(CommandHandler("unwatch", cmd_unwatch))
    application.add_handler(CommandHandler("watchlist", cmd_watchlist))
    # C2: trending & earnings
    application.add_handler(CommandHandler("trending", cmd_trending))
    application.add_handler(CommandHandler("earnings", cmd_earnings))
    # Session monitor
    application.add_handler(CommandHandler("session", cmd_session))
    # Callback handler (must be last)
    application.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("Starting Telegram bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
