"""5-filter binary scoring engine (77% win rate backtested)."""

from scoring_engine.config import WATCHLIST


def compute_score(ticker: str, technicals: dict) -> dict:
    """Compute 5-filter binary score for a ticker.

    Returns dict with score (0-5), filters detail, and all raw values.
    """
    cfg = WATCHLIST.get(ticker, {})
    price = technicals.get("price", 0)
    ma = technicals.get("moving_averages", {})
    sma_20 = ma.get("sma_20")
    sma_200 = ma.get("sma_200")
    rsi_14 = technicals.get("rsi_14")
    atr_14 = technicals.get("atr_14")
    trend_5d = technicals.get("trend_5d")

    # Filter 1: Price > SMA20
    f_sma20 = bool(sma_20 and price > sma_20)

    # Filter 2: 5-day trend > ticker threshold
    t5d_threshold = cfg.get("t5d_threshold", 2.0)
    f_trend5d = bool(trend_5d is not None and trend_5d > t5d_threshold)

    # Filter 3: RSI < ticker threshold (not overbought)
    rsi_threshold = cfg.get("rsi_threshold", 55)
    f_rsi = bool(rsi_14 is not None and rsi_14 < rsi_threshold)

    # Filter 4: Price > SMA200 (if required for this ticker)
    require_sma200 = cfg.get("require_sma200", True)
    if require_sma200:
        f_sma200 = bool(sma_200 and price > sma_200)
    else:
        f_sma200 = True  # Not required = auto-pass

    # Filter 5: ATR relative < 2.5% (low volatility)
    atr_relative = (atr_14 / price * 100) if (atr_14 and price) else None
    f_atr = bool(atr_relative is not None and atr_relative < 2.5)

    filters = {
        "price_above_sma20": f_sma20,
        "trend_5d_positive": f_trend5d,
        "rsi_below_threshold": f_rsi,
        "price_above_sma200": f_sma200,
        "atr_relative_ok": f_atr,
    }

    score = sum(1 for v in filters.values() if v)

    return {
        "ticker": ticker,
        "market": cfg.get("market", "US"),
        "price": price,
        "score": score,
        "max_score": 5,
        "filters": filters,
        "values": {
            "sma_20": sma_20,
            "sma_200": sma_200,
            "rsi_14": rsi_14,
            "atr_14": atr_14,
            "atr_relative": round(atr_relative, 2) if atr_relative else None,
            "trend_5d": trend_5d,
            "rsi_threshold": rsi_threshold,
            "t5d_threshold": t5d_threshold,
        },
    }
