"""Technical indicators computed from yfinance OHLCV data (pandas/numpy only)."""

import asyncio
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from mcp_market_data.tools._ticker_pool import get_ticker

router = APIRouter(tags=["Technicals"])

_cache = {}
CACHE_TTL = 300  # 5 min


def _get_cached(key: str) -> dict | None:
    if key in _cache:
        entry = _cache[key]
        if datetime.now() < entry["expires_at"]:
            return entry["data"]
        del _cache[key]
    return None


def _set_cache(key: str, data: dict) -> None:
    _cache[key] = {"data": data, "expires_at": datetime.now() + timedelta(seconds=CACHE_TTL)}


# --------------- Indicator calculations ---------------

def _rsi(series: pd.Series, period: int = 14) -> float | None:
    """Wilder's smoothed RSI."""
    if len(series) < period + 1:
        return None
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return round(float(val), 2) if not np.isnan(val) else None


def _rsi_signal(rsi_val: float | None) -> str:
    if rsi_val is None:
        return "neutral"
    if rsi_val >= 70:
        return "overbought"
    if rsi_val <= 30:
        return "oversold"
    return "neutral"


def _macd(close: pd.Series) -> dict | None:
    if len(close) < 26:
        return None
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line
    m = float(macd_line.iloc[-1])
    s = float(signal_line.iloc[-1])
    h = float(histogram.iloc[-1])
    signal_type = "bullish" if h > 0 else "bearish"
    return {"macd": round(m, 3), "signal": round(s, 3), "histogram": round(h, 3), "signal_type": signal_type}


def _bollinger(close: pd.Series, period: int = 20, num_std: float = 2.0) -> dict | None:
    if len(close) < period:
        return None
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = sma + num_std * std
    lower = sma - num_std * std
    mid = float(sma.iloc[-1])
    up = float(upper.iloc[-1])
    lo = float(lower.iloc[-1])
    price = float(close.iloc[-1])
    bandwidth = round((up - lo) / mid, 4) if mid else 0
    if price <= lo:
        position = "below_lower"
    elif price <= lo + (mid - lo) * 0.3:
        position = "near_lower"
    elif price >= up:
        position = "above_upper"
    elif price >= up - (up - mid) * 0.3:
        position = "near_upper"
    else:
        position = "middle"
    return {"upper": round(up, 2), "middle": round(mid, 2), "lower": round(lo, 2),
            "position": position, "bandwidth": bandwidth}


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float | None:
    if len(close) < period + 1:
        return None
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr_val = tr.ewm(alpha=1 / period, min_periods=period).mean().iloc[-1]
    return round(float(atr_val), 2) if not np.isnan(atr_val) else None


def _stochastic(high: pd.Series, low: pd.Series, close: pd.Series, k_period: int = 14, d_period: int = 3) -> dict | None:
    if len(close) < k_period:
        return None
    lowest_low = low.rolling(k_period).min()
    highest_high = high.rolling(k_period).max()
    k = 100 * (close - lowest_low) / (highest_high - lowest_low)
    d = k.rolling(d_period).mean()
    k_val = float(k.iloc[-1])
    d_val = float(d.iloc[-1])
    if np.isnan(k_val):
        return None
    signal = "oversold" if k_val < 20 else ("overbought" if k_val > 80 else "neutral")
    return {"k": round(k_val, 2), "d": round(d_val, 2), "signal": signal}


def _support_resistance_levels(hist: pd.DataFrame, n_levels: int = 3) -> dict:
    """Pivot points + local min/max clustering."""
    close = hist["Close"]
    high = hist["High"]
    low = hist["Low"]
    last_price = float(close.iloc[-1])

    # Classic pivot points from last complete bar
    p = (float(high.iloc[-2]) + float(low.iloc[-2]) + float(close.iloc[-2])) / 3
    r1 = 2 * p - float(low.iloc[-2])
    r2 = p + (float(high.iloc[-2]) - float(low.iloc[-2]))
    s1 = 2 * p - float(high.iloc[-2])
    s2 = p - (float(high.iloc[-2]) - float(low.iloc[-2]))

    # Local swing lows and highs (window=5)
    window = 5
    local_mins = low[(low.shift(window) > low) & (low.shift(-window) > low)]
    local_maxs = high[(high.shift(window) < high) & (high.shift(-window) < high)]

    all_supports = sorted(set([round(float(v), 2) for v in local_mins] + [round(s1, 2), round(s2, 2)]))
    all_resistances = sorted(set([round(float(v), 2) for v in local_maxs] + [round(r1, 2), round(r2, 2)]))

    supports = [s for s in all_supports if s < last_price][-n_levels:]
    resistances = [r for r in all_resistances if r > last_price][:n_levels]

    return {"supports": supports, "resistances": resistances, "pivot": round(p, 2)}


def _generate_summary(rsi_val, rsi_sig, stoch, boll, macd_data, ma_trend) -> str:
    signals = []
    if rsi_sig == "oversold":
        signals.append(f"RSI {rsi_val}")
    elif rsi_sig == "overbought":
        signals.append(f"RSI {rsi_val}")
    if stoch and stoch["signal"] == "oversold":
        signals.append(f"Stochastic {stoch['k']}")
    elif stoch and stoch["signal"] == "overbought":
        signals.append(f"Stochastic {stoch['k']}")
    if boll and boll["position"] in ("below_lower", "near_lower"):
        signals.append("prix pres du Bollinger inferieur")
    elif boll and boll["position"] in ("above_upper", "near_upper"):
        signals.append("prix pres du Bollinger superieur")

    if rsi_sig == "oversold":
        label = "OVERSOLD"
        action = "Signal technique d'achat potentiel."
    elif rsi_sig == "overbought":
        label = "OVERBOUGHT"
        action = "Signal technique de vente potentiel."
    elif macd_data and macd_data["signal_type"] == "bullish" and ma_trend == "bullish":
        label = "BULLISH"
        action = "Tendance haussiere confirmee par MACD et moyennes mobiles."
    elif macd_data and macd_data["signal_type"] == "bearish" and ma_trend == "bearish":
        label = "BEARISH"
        action = "Tendance baissiere confirmee par MACD et moyennes mobiles."
    else:
        label = "NEUTRAL"
        action = "Pas de signal technique fort."

    detail = " + ".join(signals) if signals else "Indicateurs dans la zone neutre"
    return f"{label} — {detail}. {action}"


# --------------- Sync data fetchers ---------------

def _compute_technicals(ticker: str, period: str) -> dict:
    t = get_ticker(ticker)
    hist = t.history(period=period)
    if hist.empty:
        raise ValueError(f"No data for {ticker}")

    close = hist["Close"]
    high = hist["High"]
    low = hist["Low"]
    volume = hist["Volume"]

    last_price = round(float(close.iloc[-1]), 2)

    # 5-day trend
    trend_5d = None
    if len(close) >= 6:
        price_5d_ago = float(close.iloc[-6])
        trend_5d = round((last_price - price_5d_ago) / price_5d_ago * 100, 2)

    # RSI
    rsi_val = _rsi(close)
    rsi_sig = _rsi_signal(rsi_val)

    # MACD
    macd_data = _macd(close)

    # Moving averages
    sma_20 = round(float(close.rolling(20).mean().iloc[-1]), 2) if len(close) >= 20 else None
    sma_50 = round(float(close.rolling(50).mean().iloc[-1]), 2) if len(close) >= 50 else None
    sma_200 = round(float(close.rolling(200).mean().iloc[-1]), 2) if len(close) >= 200 else None
    ema_12 = round(float(close.ewm(span=12, adjust=False).mean().iloc[-1]), 2) if len(close) >= 12 else None
    ema_26 = round(float(close.ewm(span=26, adjust=False).mean().iloc[-1]), 2) if len(close) >= 26 else None

    # Trend from SMAs
    if sma_50 and sma_200:
        ma_trend = "bullish" if sma_50 > sma_200 else "bearish"
    elif sma_20 and sma_50:
        ma_trend = "bullish" if sma_20 > sma_50 else "bearish"
    else:
        ma_trend = "neutral"

    # Bollinger
    boll = _bollinger(close)

    # Volume
    current_vol = int(volume.iloc[-1])
    avg_vol_20 = int(volume.rolling(20).mean().iloc[-1]) if len(volume) >= 20 else current_vol
    rel_vol = round(current_vol / avg_vol_20, 2) if avg_vol_20 > 0 else 1.0

    # ATR
    atr_val = _atr(high, low, close)

    # Stochastic
    stoch = _stochastic(high, low, close)

    # Support/Resistance
    sr = _support_resistance_levels(hist) if len(hist) >= 12 else {"supports": [], "resistances": [], "pivot": None}

    # Short interest (FINRA, updated ~every 2 weeks)
    info = t.info
    short_interest = None
    shares_short = info.get("sharesShort")
    if shares_short:
        short_interest = {
            "shares_short": shares_short,
            "short_ratio": info.get("shortRatio"),
            "short_percent_of_float": info.get("shortPercentOfFloat"),
            "shares_short_prior_month": info.get("sharesShortPriorMonth"),
            "date": info.get("dateShortInterest"),
        }

    summary = _generate_summary(rsi_val, rsi_sig, stoch, boll, macd_data, ma_trend)

    return {
        "ticker": ticker,
        "price": last_price,
        "rsi_14": rsi_val,
        "rsi_signal": rsi_sig,
        "macd": macd_data,
        "moving_averages": {
            "sma_20": sma_20, "sma_50": sma_50, "sma_200": sma_200,
            "ema_12": ema_12, "ema_26": ema_26, "trend": ma_trend,
        },
        "bollinger": boll,
        "volume": {"current": current_vol, "avg_20d": avg_vol_20, "relative": rel_vol},
        "atr_14": atr_val,
        "trend_5d": trend_5d,
        "stochastic": stoch,
        "support_resistance": sr,
        "short_interest": short_interest,
        "summary": summary,
    }


def _compute_support_resistance(ticker: str, period: str) -> dict:
    t = get_ticker(ticker)
    hist = t.history(period=period)
    if hist.empty:
        raise ValueError(f"No data for {ticker}")
    sr = _support_resistance_levels(hist, n_levels=5)
    sr["ticker"] = ticker
    sr["price"] = round(float(hist["Close"].iloc[-1]), 2)
    return sr


# --------------- Endpoints ---------------

@router.get("/stock/technicals/{ticker}")
async def get_technicals(
    ticker: str,
    period: str = Query("6mo", description="Period: 3mo,6mo,1y,2y"),
):
    """Get all technical indicators (RSI, MACD, Bollinger, SMA, Stochastic, ATR, support/resistance) for a ticker."""
    ticker = ticker.upper()
    cache_key = f"technicals:{ticker}:{period}"
    cached = _get_cached(cache_key)
    if cached:
        return cached
    try:
        result = await asyncio.to_thread(_compute_technicals, ticker, period)
        _set_cache(cache_key, result)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error computing technicals for {ticker}: {e}")


@router.get("/stock/support-resistance/{ticker}")
async def get_support_resistance(
    ticker: str,
    period: str = Query("1y", description="Period: 6mo,1y,2y"),
):
    """Get support and resistance levels (pivot points + swing highs/lows) for a ticker."""
    ticker = ticker.upper()
    cache_key = f"sr:{ticker}:{period}"
    cached = _get_cached(cache_key)
    if cached:
        return cached
    try:
        result = await asyncio.to_thread(_compute_support_resistance, ticker, period)
        _set_cache(cache_key, result)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error computing S/R for {ticker}: {e}")
