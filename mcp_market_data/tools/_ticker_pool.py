"""Shared yfinance Ticker pool with connection reuse.

Instead of creating a new yf.Ticker() (and HTTP session) per request,
we cache Ticker objects by symbol and reuse them.
"""

import threading
import yfinance as yf

_lock = threading.Lock()
_pool: dict[str, yf.Ticker] = {}


def get_ticker(symbol: str) -> yf.Ticker:
    """Get or create a cached yf.Ticker for a symbol."""
    symbol = symbol.upper()
    if symbol not in _pool:
        with _lock:
            if symbol not in _pool:
                _pool[symbol] = yf.Ticker(symbol)
    return _pool[symbol]
