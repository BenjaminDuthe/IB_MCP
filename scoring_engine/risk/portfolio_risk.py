"""Portfolio-level risk checks: sector concentration, correlation, drawdown."""

import asyncio
import logging

from scoring_engine.config import (
    TICKER_SECTORS,
    MAX_SECTOR_EXPOSURE_PCT,
    DRAWDOWN_REDUCE_THRESHOLD,
    PORTFOLIO_VALUE,
)

logger = logging.getLogger(__name__)

# Thread-safe cycle state
_lock = asyncio.Lock()
_active_buy_signals: list[str] = []


async def reset_cycle():
    """Reset per-cycle state. Called at start of scan_tickers."""
    async with _lock:
        _active_buy_signals.clear()


async def register_buy(ticker: str):
    """Register a BUY signal in the current scan cycle."""
    async with _lock:
        _active_buy_signals.append(ticker)


async def check_sector_concentration(ticker: str) -> dict:
    """Check if adding this ticker would exceed sector limits."""
    async with _lock:
        sector = TICKER_SECTORS.get(ticker, "unknown")
        same_sector_buys = [t for t in _active_buy_signals if TICKER_SECTORS.get(t) == sector]
        count = len(same_sector_buys)

    if count >= 3:
        return {
            "passed": False,
            "reason": f"Sector '{sector}' deja {count} signaux BUY ({', '.join(same_sector_buys)})",
            "sector": sector,
            "count": count,
        }

    return {"passed": True, "sector": sector, "count": count}


async def check_correlation_risk(ticker: str) -> dict:
    """Warn if multiple correlated tickers are signaling BUY simultaneously."""
    async with _lock:
        sector = TICKER_SECTORS.get(ticker, "unknown")
        correlated = [t for t in _active_buy_signals if TICKER_SECTORS.get(t) == sector and t != ticker]

    if correlated:
        return {
            "warning": True,
            "message": f"Correle avec {', '.join(correlated)} (meme secteur: {sector})",
            "correlated_tickers": correlated,
        }
    return {"warning": False}


def check_drawdown_protection(current_drawdown_pct: float = 0.0) -> dict:
    """If portfolio drawdown exceeds threshold, suggest reduced position sizing."""
    if abs(current_drawdown_pct) >= DRAWDOWN_REDUCE_THRESHOLD:
        multiplier = 0.5
        return {
            "reduce": True,
            "multiplier": multiplier,
            "reason": f"Drawdown {current_drawdown_pct:.1f}% > seuil {DRAWDOWN_REDUCE_THRESHOLD}%",
        }
    return {"reduce": False, "multiplier": 1.0}


def get_active_signals() -> list[str]:
    """Get a copy of active buy signals (for API endpoint)."""
    return list(_active_buy_signals)
