"""Position sizing: Kelly criterion + volatility scaling."""

import math

from scoring_engine.config import PORTFOLIO_VALUE, MAX_POSITION_RISK_PCT


def kelly_fraction(win_rate: float, avg_win_pct: float, avg_loss_pct: float) -> float:
    """Kelly criterion: f* = (p*b - q) / b where b = avg_win/avg_loss, p = win_rate, q = 1-p."""
    if avg_loss_pct == 0 or win_rate <= 0:
        return 0.0
    b = abs(avg_win_pct / avg_loss_pct)
    q = 1 - win_rate
    f = (win_rate * b - q) / b
    # Half-Kelly for safety
    return max(0.0, min(0.25, f * 0.5))


def volatility_adjusted_size(
    base_dollars: float, atr_pct: float, target_risk_pct: float = None,
) -> float:
    """Scale position size inversely to volatility (ATR %)."""
    if target_risk_pct is None:
        target_risk_pct = MAX_POSITION_RISK_PCT
    if atr_pct <= 0:
        return base_dollars
    # If ATR is 2%, and target risk is 2%, multiplier = 1.0
    # If ATR is 4%, multiplier = 0.5 (reduce size)
    multiplier = target_risk_pct / atr_pct
    return base_dollars * min(2.0, max(0.25, multiplier))


def compute_position_size(
    confidence: int,
    price: float,
    atr_pct: float | None = None,
    win_rate: float = 0.77,
    portfolio_value: float = None,
) -> dict:
    """Compute suggested position size.

    Returns {shares, dollar_value, risk_pct, method}.
    """
    pv = portfolio_value or PORTFOLIO_VALUE
    if price <= 0:
        return {"shares": 0, "dollar_value": 0, "risk_pct": 0, "method": "invalid_price"}

    # Base: Kelly fraction of portfolio
    # Assume avg_win = confidence/100 * 5% and avg_loss = (1-confidence/100) * 3%
    avg_win = (confidence / 100) * 5.0
    avg_loss = max(1.0, (1 - confidence / 100) * 3.0)
    kelly_f = kelly_fraction(win_rate, avg_win, avg_loss)
    base_dollars = pv * kelly_f

    # Volatility adjustment
    if atr_pct and atr_pct > 0:
        adjusted_dollars = volatility_adjusted_size(base_dollars, atr_pct)
        method = "kelly_vol_adjusted"
    else:
        adjusted_dollars = base_dollars
        method = "kelly"

    # Cap at MAX_POSITION_RISK_PCT of portfolio
    max_dollars = pv * (MAX_POSITION_RISK_PCT / 100)
    final_dollars = min(adjusted_dollars, max_dollars)

    shares = max(1, math.floor(final_dollars / price))
    actual_dollars = shares * price
    risk_pct = (actual_dollars / pv) * 100

    return {
        "shares": shares,
        "dollar_value": round(actual_dollars, 2),
        "risk_pct": round(risk_pct, 2),
        "kelly_fraction": round(kelly_f, 4),
        "method": method,
    }
