"""Model drift detection — alert if win rate drops below threshold."""

import logging

from scoring_engine.config import WIN_RATE_DRIFT_THRESHOLD
from scoring_engine.feedback.tracker import compute_signal_accuracy
from scoring_engine.alerter import send_telegram, send_discord_embed, COLOR_SELL

logger = logging.getLogger(__name__)


async def check_drift() -> dict:
    """Check if model performance has drifted below acceptable threshold.

    Returns {drifted, win_rate, threshold, signal_count}.
    """
    accuracy = await compute_signal_accuracy()

    if accuracy.get("evaluated", 0) < 10:
        return {
            "drifted": False,
            "win_rate": accuracy.get("win_rate", 0),
            "threshold": WIN_RATE_DRIFT_THRESHOLD * 100,
            "signal_count": accuracy.get("evaluated", 0),
            "message": "Pas assez de signaux pour détecter le drift",
        }

    drifted = (accuracy.get("win_rate", 0) / 100) < WIN_RATE_DRIFT_THRESHOLD

    result = {
        "drifted": drifted,
        "win_rate": accuracy.get("win_rate", 0),
        "threshold": WIN_RATE_DRIFT_THRESHOLD * 100,
        "signal_count": accuracy.get("evaluated", 0),
    }

    if drifted:
        msg = (
            f"⚠️ DRIFT DETECTE — Win rate {accuracy['win_rate']:.0f}% "
            f"< seuil {WIN_RATE_DRIFT_THRESHOLD*100:.0f}% "
            f"(sur {accuracy['evaluated']} signaux)"
        )
        result["message"] = msg
        logger.warning(msg)
        await send_telegram(f"⚠️ <b>MODEL DRIFT</b>\n\n{msg}")
        await send_discord_embed([{
            "title": "⚠️ Model Drift Détecté",
            "description": msg,
            "color": COLOR_SELL,
        }])
    else:
        result["message"] = f"OK — Win rate {accuracy['win_rate']:.0f}%"

    return result
