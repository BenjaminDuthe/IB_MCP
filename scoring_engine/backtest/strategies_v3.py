"""V3 strategies: RSI(2), IBS, Connors RSI, streak — pro-grade backtesting.

These are the strategies actually used by quantitative traders:
- Connors RSI(2): 75% win rate documented on S&P500
- IBS (Internal Bar Strength): simple but effective mean reversion
- Streak: consecutive down days as entry signal
- Combined: multiple confirming factors = highest win rates
"""

import logging
from collections import defaultdict

import numpy as np
import pandas as pd

from scoring_engine.backtest.replayer import _query

logger = logging.getLogger(__name__)


# --- Indicator calculations from OHLCV ---

def compute_rsi(close: pd.Series, period: int = 2) -> pd.Series:
    """RSI with configurable period. Default 2 (Connors style)."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def compute_ibs(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Internal Bar Strength: (Close - Low) / (High - Low). Range 0-1."""
    denom = high - low
    return ((close - low) / denom).where(denom > 0, 0.5)


def compute_streak(close: pd.Series) -> pd.Series:
    """Count consecutive down days (negative = down streak, positive = up streak)."""
    changes = close.diff()
    streak = pd.Series(0, index=close.index, dtype=int)
    for i in range(1, len(close)):
        if changes.iloc[i] < 0:
            streak.iloc[i] = min(streak.iloc[i - 1], 0) - 1
        elif changes.iloc[i] > 0:
            streak.iloc[i] = max(streak.iloc[i - 1], 0) + 1
        else:
            streak.iloc[i] = 0
    return streak


def compute_percentile_rank(close: pd.Series, period: int = 100) -> pd.Series:
    """Percentile rank of current close within last N bars."""
    def _rank(window):
        if len(window) < 2:
            return 50
        current = window.iloc[-1]
        return (window < current).sum() / (len(window) - 1) * 100
    return close.rolling(period).apply(_rank, raw=False)


def compute_connors_rsi(close: pd.Series) -> pd.Series:
    """Connors RSI = average(RSI(3), streak RSI(2), percentile rank)."""
    rsi3 = compute_rsi(close, 3)
    streak = compute_streak(close)
    streak_rsi = compute_rsi(streak.astype(float), 2)
    pct_rank = compute_percentile_rank(close, 100)
    return (rsi3 + streak_rsi + pct_rank) / 3


async def _get_sp500_df() -> pd.DataFrame:
    rows = await _query("SELECT time, close FROM ohlcv WHERE ticker='^GSPC' ORDER BY time ASC")
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df.set_index("time")
    return df


async def _get_ticker_df(ticker: str) -> pd.DataFrame:
    rows = await _query(
        f"SELECT time, open, high, low, close, volume FROM ohlcv "
        f"WHERE ticker='{ticker}' ORDER BY time ASC"
    )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df.set_index("time")
    return df


def _build_factors(df: pd.DataFrame, sp500: pd.DataFrame) -> pd.DataFrame:
    """Compute all factors for a ticker DataFrame."""
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    f = pd.DataFrame(index=df.index)
    f["close"] = close

    # RSI variants
    f["rsi2"] = compute_rsi(close, 2)
    f["rsi14"] = compute_rsi(close, 14)

    # IBS
    f["ibs"] = compute_ibs(high, low, close)

    # Streak
    f["streak"] = compute_streak(close)

    # Connors RSI
    f["connors_rsi"] = compute_connors_rsi(close)

    # Moving averages
    f["sma20"] = close.rolling(20).mean()
    f["sma50"] = close.rolling(50).mean()
    f["sma200"] = close.rolling(200).mean()

    # Trend filter
    f["above_sma200"] = close > f["sma200"]
    f["trend_aligned"] = (f["sma20"] > f["sma50"]) & (f["sma50"] > f["sma200"])

    # Momentum
    f["mom_1m"] = close.pct_change(20) * 100
    f["mom_3m"] = close.pct_change(60) * 100
    f["mom_6m"] = close.pct_change(120) * 100

    # Volume ratio
    f["vol_ratio"] = volume / volume.rolling(20).mean()

    # Bollinger
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    f["bb_lower"] = bb_mid - 2 * bb_std
    f["near_bb_lower"] = close <= f["bb_lower"] * 1.02

    # ATR relative
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, min_periods=14).mean()
    f["atr_rel"] = (atr / close * 100)

    # Relative strength vs S&P500
    if not sp500.empty:
        sp_close = sp500["close"].reindex(df.index, method="ffill")
        f["rel_str_1m"] = close.pct_change(20) - sp_close.pct_change(20)
    else:
        f["rel_str_1m"] = 0

    return f.dropna(subset=["sma200"])


# --- Strategy definitions ---

STRATEGIES_V3 = {
    # === Connors RSI(2) — the gold standard ===
    "connors_rsi2_buy_5": lambda f: (f["rsi2"] < 5) & f["above_sma200"],
    "connors_rsi2_buy_10": lambda f: (f["rsi2"] < 10) & f["above_sma200"],
    "connors_rsi2_buy_15": lambda f: (f["rsi2"] < 15) & f["above_sma200"],

    # === IBS mean reversion ===
    "ibs_extreme": lambda f: (f["ibs"] < 0.1) & f["above_sma200"],
    "ibs_low": lambda f: (f["ibs"] < 0.2) & f["above_sma200"],
    "ibs_low_rsi2": lambda f: (f["ibs"] < 0.2) & (f["rsi2"] < 20) & f["above_sma200"],

    # === Connors RSI composite ===
    "connors_composite_10": lambda f: (f["connors_rsi"] < 10) & f["above_sma200"],
    "connors_composite_15": lambda f: (f["connors_rsi"] < 15) & f["above_sma200"],
    "connors_composite_20": lambda f: (f["connors_rsi"] < 20) & f["above_sma200"],

    # === Streak-based ===
    "streak_3down_sma200": lambda f: (f["streak"] <= -3) & f["above_sma200"],
    "streak_3down_ibs": lambda f: (f["streak"] <= -3) & (f["ibs"] < 0.3),
    "streak_2down_rsi2_10": lambda f: (f["streak"] <= -2) & (f["rsi2"] < 10) & f["above_sma200"],

    # === Pro composite (multiple confirmations) ===
    "pro_max": lambda f: (f["rsi2"] < 10) & (f["ibs"] < 0.3) & (f["streak"] <= -2) & f["above_sma200"],
    "pro_conservative": lambda f: (f["rsi2"] < 15) & f["above_sma200"] & (f["mom_3m"] > 0),
    "pro_relative": lambda f: (f["rsi2"] < 15) & f["above_sma200"] & (f["rel_str_1m"] > 0),

    # === Momentum ===
    "momentum_triple": lambda f: (f["mom_1m"] > 0) & (f["mom_3m"] > 0) & (f["mom_6m"] > 0) & f["above_sma200"],
    "momentum_trend": lambda f: f["trend_aligned"] & (f["mom_1m"] > 0) & (f["vol_ratio"] > 1.0),

    # === Bollinger + RSI ===
    "bb_rsi2_oversold": lambda f: f["near_bb_lower"] & (f["rsi2"] < 10) & f["above_sma200"],

    # === Baseline comparison ===
    "baseline_old_score3": lambda f: (f["rsi14"] < 55) & f["above_sma200"] & (f["atr_rel"] < 2.5),
}


async def run_v3_backtest(tickers: list[str], horizons: list[int] = None) -> dict:
    """Run all v3 strategies on all tickers."""
    if horizons is None:
        horizons = [5, 10, 20, 60]

    sp500 = await _get_sp500_df()

    strategy_results = {
        name: {h: {"total": 0, "profitable": 0, "returns": []} for h in horizons}
        for name in STRATEGIES_V3
    }

    tickers_done = 0
    for ticker in tickers:
        df = await _get_ticker_df(ticker)
        if df.empty or len(df) < 250:
            continue

        factors = _build_factors(df, sp500)
        if factors.empty:
            continue

        closes = factors["close"].values
        indices = list(range(len(factors)))

        for strat_name, condition in STRATEGIES_V3.items():
            try:
                mask = condition(factors)
            except Exception:
                continue

            signal_indices = [i for i in indices if mask.iloc[i]]

            for i in signal_indices:
                entry_price = closes[i]
                if entry_price <= 0:
                    continue
                for h in horizons:
                    exit_idx = i + h
                    if exit_idx >= len(closes):
                        continue
                    exit_price = closes[exit_idx]
                    ret = (exit_price - entry_price) / entry_price * 100
                    bucket = strategy_results[strat_name][h]
                    bucket["total"] += 1
                    if ret > 0:
                        bucket["profitable"] += 1
                    bucket["returns"].append(ret)

        tickers_done += 1

    # Compute summary
    summary = {}
    for strat_name in STRATEGIES_V3:
        summary[strat_name] = {}
        for h in horizons:
            b = strategy_results[strat_name][h]
            total = b["total"]
            if total >= 20:
                rets = b["returns"]
                win_rate = b["profitable"] / total * 100
                avg_ret = sum(rets) / len(rets)
                rets_sorted = sorted(rets)
                median_ret = rets_sorted[len(rets_sorted) // 2]
                max_gain = max(rets)
                max_loss = min(rets)
            else:
                win_rate = avg_ret = median_ret = max_gain = max_loss = 0
            summary[strat_name][f"{h}d"] = {
                "signals": total,
                "win_rate": round(win_rate, 1),
                "avg_return": round(avg_ret, 2),
                "median_return": round(median_ret, 2),
            }

    ranked = sorted(summary.items(), key=lambda x: x[1].get("20d", {}).get("win_rate", 0), reverse=True)

    return {
        "tickers_tested": tickers_done,
        "strategies_tested": len(STRATEGIES_V3),
        "ranked": [{"strategy": name, **data} for name, data in ranked],
    }
