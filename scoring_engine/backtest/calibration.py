"""Calibrated conviction: replace Claude's subjective % with data-driven %.

After backtesting, we know:
  "Score 4/5 → historically 78% profitable at 10 days, avg return +3.2%"

This module stores the calibration table and provides a lookup function.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

# Default calibration (will be overwritten after first backtest)
# Format: {score_level: {horizon_days: {"win_rate": %, "avg_return": %}}}
DEFAULT_CALIBRATION = {
    "score_3": {"5d": {"win_rate": 55, "avg_return": 0.8}, "10d": {"win_rate": 57, "avg_return": 1.2}, "20d": {"win_rate": 58, "avg_return": 1.5}},
    "score_4": {"5d": {"win_rate": 65, "avg_return": 1.5}, "10d": {"win_rate": 68, "avg_return": 2.5}, "20d": {"win_rate": 70, "avg_return": 3.5}},
    "score_5": {"5d": {"win_rate": 72, "avg_return": 2.0}, "10d": {"win_rate": 75, "avg_return": 3.5}, "20d": {"win_rate": 78, "avg_return": 5.0}},
}

CALIBRATION_FILE = os.environ.get("CALIBRATION_FILE", "/tmp/calibration.json")

_calibration = None


def load_calibration() -> dict:
    """Load calibration from file or use defaults."""
    global _calibration
    if _calibration:
        return _calibration
    try:
        with open(CALIBRATION_FILE) as f:
            _calibration = json.load(f)
            logger.info("Loaded calibration from %s", CALIBRATION_FILE)
    except FileNotFoundError:
        _calibration = DEFAULT_CALIBRATION
        logger.info("Using default calibration (no backtest run yet)")
    return _calibration


def save_calibration(data: dict):
    """Save calibration after backtest."""
    global _calibration
    _calibration = data
    try:
        with open(CALIBRATION_FILE, "w") as f:
            json.dump(data, f, indent=2)
        logger.info("Saved calibration to %s", CALIBRATION_FILE)
    except Exception as e:
        logger.error("Failed to save calibration: %s", e)


def get_calibrated_conviction(score: int, horizon_days: int = 10) -> dict:
    """Get data-driven conviction for a score level.

    Returns {"win_rate": 68.5, "avg_return": 2.3, "source": "backtest_78_tickers"}
    """
    cal = load_calibration()
    key = f"score_{score}"
    h_key = f"{horizon_days}d"

    if key in cal and h_key in cal[key]:
        data = cal[key][h_key]
        return {
            "win_rate": data["win_rate"],
            "avg_return": data["avg_return"],
            "conviction": data["win_rate"],  # conviction = win_rate from backtest
            "source": "backtest" if _calibration != DEFAULT_CALIBRATION else "default",
            "horizon_days": horizon_days,
        }

    return {"win_rate": 50, "avg_return": 0, "conviction": 50, "source": "unknown", "horizon_days": horizon_days}
