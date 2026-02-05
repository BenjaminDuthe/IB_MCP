import os
import json
from telegram_bot.models import TradeSignal, SafetyCheckResult, TradeAction
from telegram_bot.db import get_system_state, get_daily_order_count, get_daily_pnl


MAX_ORDER_VALUE_USD = float(os.environ.get("MAX_ORDER_VALUE_USD", "10000"))
MAX_DAILY_ORDERS = int(os.environ.get("MAX_DAILY_ORDERS", "10"))
MAX_DAILY_LOSS_USD = float(os.environ.get("MAX_DAILY_LOSS_USD", "2000"))
MAX_POSITION_PCT = float(os.environ.get("MAX_POSITION_PCT", "25"))


async def check_safety(signal: TradeSignal) -> SafetyCheckResult:
    """Run all safety checks on a trade signal. Returns SafetyCheckResult."""
    checks = {}

    # 1. Arret d'urgence
    kill_switch = await get_system_state("kill_switch")
    if kill_switch == "active":
        return SafetyCheckResult(
            passed=False,
            checks={"arret_urgence": "BLOQUE"},
            blocked_reason="Arret d'urgence actif. Utilise /resume pour reactiver.",
        )
    checks["arret_urgence"] = "OK"

    # 2. Valeur de l'ordre
    if signal.price and signal.quantity:
        order_value = signal.price * signal.quantity
        if order_value > MAX_ORDER_VALUE_USD:
            return SafetyCheckResult(
                passed=False,
                checks={**checks, "valeur_ordre": f"BLOQUE (${order_value:.0f} > ${MAX_ORDER_VALUE_USD:.0f})"},
                blocked_reason=f"Valeur de l'ordre ${order_value:.0f} depasse le maximum ${MAX_ORDER_VALUE_USD:.0f}.",
            )
        checks["valeur_ordre"] = f"OK (${order_value:.0f})"
    else:
        checks["valeur_ordre"] = "IGNORE (pas de prix/qte)"

    # 3. Nombre d'ordres du jour
    daily_orders = await get_daily_order_count()
    if daily_orders >= MAX_DAILY_ORDERS:
        return SafetyCheckResult(
            passed=False,
            checks={**checks, "ordres_jour": f"BLOQUE ({daily_orders}/{MAX_DAILY_ORDERS})"},
            blocked_reason=f"Limite d'ordres journaliere atteinte ({daily_orders}/{MAX_DAILY_ORDERS}).",
        )
    checks["ordres_jour"] = f"OK ({daily_orders}/{MAX_DAILY_ORDERS})"

    # 4. Limite de pertes du jour
    daily_pnl = await get_daily_pnl()
    if daily_pnl < -MAX_DAILY_LOSS_USD:
        return SafetyCheckResult(
            passed=False,
            checks={**checks, "pertes_jour": f"BLOQUE (${daily_pnl:.0f} < -${MAX_DAILY_LOSS_USD:.0f})"},
            blocked_reason=f"Limite de pertes journaliere depassee (${daily_pnl:.0f}).",
        )
    checks["pertes_jour"] = f"OK (${daily_pnl:.0f})"

    # 5. Stop-loss obligatoire pour les achats
    if signal.action == TradeAction.BUY and signal.stop_loss is None:
        return SafetyCheckResult(
            passed=False,
            checks={**checks, "stop_loss": "BLOQUE (manquant)"},
            blocked_reason="Un stop-loss est obligatoire pour les ordres d'achat.",
        )
    checks["stop_loss"] = "OK" if signal.action != TradeAction.HOLD else "N/A"

    return SafetyCheckResult(passed=True, checks=checks)


def format_safety_result(result: SafetyCheckResult) -> str:
    """Format safety check result for Telegram display."""
    lines = []
    for check, status in result.checks.items():
        icon = "✅" if "OK" in status or "N/A" in status else "❌"
        lines.append(f"  {icon} {check} : {status}")
    return "\n".join(lines)
