"""Enhanced risk management: position sizing + portfolio risk checks."""

import logging

from scoring_engine.risk.position_sizer import compute_position_size
from scoring_engine.risk.portfolio_risk import (
    check_sector_concentration,
    check_correlation_risk,
    check_drawdown_protection,
    register_buy,
)

logger = logging.getLogger(__name__)


async def enhanced_risk_check(ticker: str, score_data: dict, llm: dict) -> dict:
    """Full risk assessment before alerting a BUY signal.

    Returns {approved, position, warnings, reason}.
    """
    warnings = []

    # 1. Sector concentration
    sector_check = check_sector_concentration(ticker)
    if not sector_check["passed"]:
        return {
            "approved": False,
            "reason": sector_check["reason"],
            "position": None,
            "warnings": [sector_check["reason"]],
        }

    # 2. Correlation warning
    corr_check = check_correlation_risk(ticker)
    if corr_check.get("warning"):
        warnings.append(corr_check["message"])

    # 3. Drawdown protection
    dd_check = check_drawdown_protection()
    dd_multiplier = dd_check["multiplier"]
    if dd_check["reduce"]:
        warnings.append(dd_check["reason"])

    # 4. Position sizing
    atr_relative = score_data.get("values", {}).get("atr_relative")
    position = compute_position_size(
        confidence=llm.get("confidence", 50),
        price=score_data.get("price", 0),
        atr_pct=atr_relative,
    )

    # Apply drawdown multiplier
    if dd_multiplier < 1.0:
        position["shares"] = max(1, int(position["shares"] * dd_multiplier))
        position["dollar_value"] = round(position["shares"] * score_data.get("price", 0), 2)
        position["risk_pct"] = round(position["dollar_value"] / 50000 * 100, 2)

    # Register this BUY for subsequent sector checks in the same cycle
    register_buy(ticker)

    return {
        "approved": True,
        "position": position,
        "warnings": warnings,
        "reason": "approved",
    }
