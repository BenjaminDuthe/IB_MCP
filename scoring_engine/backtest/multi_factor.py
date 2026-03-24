"""Multi-factor backtester: find which COMBINATIONS of signals predict profits.

The 5-filter score alone gives 55-62%. By combining with additional factors
computed from OHLCV (momentum, volume, mean reversion, relative strength),
we can find strategies with 65-80% win rates.

Factors tested:
1. Technical score (existing 0-5)
2. Momentum 1 month (close vs close 20 days ago)
3. Momentum 3 months (close vs close 60 days ago)
4. RSI zone (oversold <30, overbought >70, neutral)
5. Volume surge (current volume vs 20-day average)
6. Volatility regime (ATR relative: low <1.5%, high >3%)
7. Relative strength vs S&P500 (outperforming or underperforming index)
8. Mean reversion signal (RSI <30 + price near bollinger lower)
9. MACD crossover (histogram sign change)
10. Trend alignment (SMA20 > SMA50 > SMA200)
"""

import asyncio
import logging
from collections import defaultdict

from scoring_engine.backtest.replayer import _query

logger = logging.getLogger(__name__)


async def _get_sp500_closes() -> dict[int, float]:
    """Get S&P500 close prices indexed by timestamp."""
    rows = await _query(
        "SELECT time, close FROM ohlcv WHERE ticker='^GSPC' ORDER BY time ASC"
    )
    return {r["time"]: r["close"] for r in rows if r.get("close")}


async def _get_ticker_data(ticker: str) -> tuple[list, list]:
    """Get OHLCV + technicals for a ticker."""
    ohlcv = await _query(
        f"SELECT time, open, high, low, close, volume FROM ohlcv "
        f"WHERE ticker='{ticker}' ORDER BY time ASC"
    )
    tech = await _query(
        f"SELECT time, rsi_14, sma_20, sma_50, sma_200, atr_14, "
        f"macd_histogram, bollinger_lower, bollinger_upper, stochastic_k "
        f"FROM technicals_history WHERE ticker='{ticker}' ORDER BY time ASC"
    )
    return ohlcv, tech


def _compute_factors(i: int, closes: list, volumes: list, tech_by_time: dict,
                     sp500: dict, ts: int, close: float, params: dict) -> dict | None:
    """Compute all factors for a single day."""
    tech = tech_by_time.get(ts)
    if not tech or not close or close <= 0:
        return None

    sma_20 = tech.get("sma_20")
    sma_50 = tech.get("sma_50")
    sma_200 = tech.get("sma_200")
    rsi = tech.get("rsi_14")
    atr = tech.get("atr_14")
    macd_hist = tech.get("macd_histogram")
    boll_lower = tech.get("bollinger_lower")
    boll_upper = tech.get("bollinger_upper")

    # --- Technical score (existing 5-filter) ---
    close_5d = closes[i - 5][1] if i >= 5 else None
    trend_5d = ((close - close_5d) / close_5d * 100) if close_5d and close_5d > 0 else None

    f1 = bool(sma_20 and close > sma_20)
    f2 = bool(trend_5d is not None and trend_5d > params.get("t5d_threshold", 2.5))
    f3 = bool(rsi is not None and rsi < params.get("rsi_threshold", 55))
    f4 = bool(sma_200 and close > sma_200) if params.get("require_sma200", True) else True
    atr_rel = (atr / close * 100) if atr and close > 0 else None
    f5 = bool(atr_rel is not None and atr_rel < 2.5)
    tech_score = sum([f1, f2, f3, f4, f5])

    # --- Momentum 1 month ---
    close_20d = closes[i - 20][1] if i >= 20 else None
    mom_1m = ((close - close_20d) / close_20d * 100) if close_20d and close_20d > 0 else None

    # --- Momentum 3 months ---
    close_60d = closes[i - 60][1] if i >= 60 else None
    mom_3m = ((close - close_60d) / close_60d * 100) if close_60d and close_60d > 0 else None

    # --- Volume surge ---
    if i >= 20 and volumes:
        recent_vols = [v for _, v in volumes[max(0, i-20):i] if v and v > 0]
        avg_vol = sum(recent_vols) / len(recent_vols) if recent_vols else 0
        cur_vol = volumes[i][1] if i < len(volumes) and volumes[i][1] else 0
        vol_surge = (cur_vol / avg_vol) if avg_vol > 0 else 1.0
    else:
        vol_surge = 1.0

    # --- Relative strength vs S&P500 ---
    sp_close = sp500.get(ts)
    sp_20d_ts = closes[i - 20][0] if i >= 20 else None
    sp_20d = sp500.get(sp_20d_ts) if sp_20d_ts else None
    if sp_close and sp_20d and close_20d and sp_20d > 0 and close_20d > 0:
        ticker_ret = (close - close_20d) / close_20d
        sp_ret = (sp_close - sp_20d) / sp_20d
        rel_strength = ticker_ret - sp_ret
    else:
        rel_strength = None

    # --- Mean reversion signal ---
    mean_rev = bool(rsi and rsi < 30 and boll_lower and close <= boll_lower * 1.02)

    # --- MACD crossover ---
    prev_ts = closes[i - 1][0] if i >= 1 else None
    prev_tech = tech_by_time.get(prev_ts) if prev_ts else None
    prev_macd = prev_tech.get("macd_histogram") if prev_tech else None
    macd_cross = bool(macd_hist and prev_macd and macd_hist > 0 and prev_macd <= 0)

    # --- Trend alignment (SMA20 > SMA50 > SMA200) ---
    trend_aligned = bool(sma_20 and sma_50 and sma_200 and sma_20 > sma_50 > sma_200)

    return {
        "tech_score": tech_score,
        "rsi": rsi,
        "mom_1m": mom_1m,
        "mom_3m": mom_3m,
        "vol_surge": vol_surge,
        "atr_rel": atr_rel,
        "rel_strength": rel_strength,
        "mean_rev": mean_rev,
        "macd_cross": macd_cross,
        "trend_aligned": trend_aligned,
    }


# --- Strategy definitions ---

STRATEGIES = {
    "baseline_score3": lambda f: f["tech_score"] >= 3,
    "baseline_score4": lambda f: f["tech_score"] >= 4,

    # Momentum + technical
    "score3_mom1m_pos": lambda f: f["tech_score"] >= 3 and f.get("mom_1m", 0) > 0,
    "score3_mom3m_pos": lambda f: f["tech_score"] >= 3 and f.get("mom_3m", 0) > 0,
    "score3_dual_mom": lambda f: f["tech_score"] >= 3 and f.get("mom_1m", 0) > 0 and f.get("mom_3m", 0) > 0,

    # Trend alignment
    "score3_trend_aligned": lambda f: f["tech_score"] >= 3 and f["trend_aligned"],
    "score4_trend_aligned": lambda f: f["tech_score"] >= 4 and f["trend_aligned"],

    # Volume confirmation
    "score3_vol_surge": lambda f: f["tech_score"] >= 3 and f.get("vol_surge", 1) > 1.5,

    # Relative strength
    "score3_outperform": lambda f: f["tech_score"] >= 3 and f.get("rel_strength", 0) > 0,
    "score3_strong_outperf": lambda f: f["tech_score"] >= 3 and f.get("rel_strength", 0) > 0.02,

    # Mean reversion (contrarian)
    "mean_reversion": lambda f: f["mean_rev"],
    "mean_rev_macd_cross": lambda f: f["mean_rev"] and f["macd_cross"],

    # MACD crossover
    "macd_cross_score3": lambda f: f["macd_cross"] and f["tech_score"] >= 3,

    # Low volatility + trend
    "low_vol_trend": lambda f: f.get("atr_rel", 5) < 1.5 and f["trend_aligned"],

    # Combined best guess
    "composite_strong": lambda f: (
        f["tech_score"] >= 3
        and f["trend_aligned"]
        and f.get("mom_1m", 0) > 0
        and f.get("rel_strength", 0) > 0
    ),
    "composite_moderate": lambda f: (
        f["tech_score"] >= 3
        and f.get("mom_1m", 0) > 0
        and f.get("rel_strength", 0) > -0.01
    ),
}


async def run_multi_factor_backtest(tickers_params: dict, horizons: list[int] = None) -> dict:
    """Test all strategies on all tickers.

    Returns performance of each strategy at each horizon.
    """
    if horizons is None:
        horizons = [5, 10, 20, 60]

    sp500 = await _get_sp500_closes()

    strategy_results = {name: {h: {"total": 0, "profitable": 0, "returns": []} for h in horizons}
                        for name in STRATEGIES}

    tickers_done = 0
    for ticker, params in tickers_params.items():
        ohlcv, tech_list = await _get_ticker_data(ticker)
        if not ohlcv or not tech_list:
            continue

        tech_by_time = {r["time"]: r for r in tech_list}
        closes = [(r["time"], r["close"]) for r in ohlcv if r.get("close")]
        volumes = [(r["time"], r.get("volume")) for r in ohlcv]
        close_by_idx = {i: (t, c) for i, (t, c) in enumerate(closes)}

        for i, (ts, close) in enumerate(closes):
            if i < 60:  # need 60 days lookback
                continue

            factors = _compute_factors(i, closes, volumes, tech_by_time, sp500, ts, close, params)
            if not factors:
                continue

            # Test each strategy
            for strat_name, condition in STRATEGIES.items():
                try:
                    if not condition(factors):
                        continue
                except (TypeError, KeyError):
                    continue

                for h in horizons:
                    future_idx = i + h
                    if future_idx not in close_by_idx:
                        continue
                    future_close = close_by_idx[future_idx][1]
                    if not future_close:
                        continue

                    ret = (future_close - close) / close * 100
                    bucket = strategy_results[strat_name][h]
                    bucket["total"] += 1
                    if ret > 0:
                        bucket["profitable"] += 1
                    bucket["returns"].append(ret)

        tickers_done += 1

    # Compute summary
    summary = {}
    for strat_name in STRATEGIES:
        summary[strat_name] = {}
        for h in horizons:
            b = strategy_results[strat_name][h]
            total = b["total"]
            if total > 10:
                win_rate = b["profitable"] / total * 100
                avg_ret = sum(b["returns"]) / len(b["returns"])
                returns_sorted = sorted(b["returns"])
                median_ret = returns_sorted[len(returns_sorted) // 2]
            else:
                win_rate = avg_ret = median_ret = 0
            summary[strat_name][f"{h}d"] = {
                "signals": total,
                "win_rate": round(win_rate, 1),
                "avg_return": round(avg_ret, 2),
                "median_return": round(median_ret, 2),
            }

    # Rank strategies by 20-day win rate
    ranked = sorted(summary.items(), key=lambda x: x[1].get("20d", {}).get("win_rate", 0), reverse=True)

    return {
        "tickers_tested": tickers_done,
        "strategies_tested": len(STRATEGIES),
        "ranked": [{"strategy": name, **data} for name, data in ranked],
    }
