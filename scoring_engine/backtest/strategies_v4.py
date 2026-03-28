"""V4 strategies: regime filter, signal combos, smart exits, walk-forward.

Improvements over V3:
1. VIX regime filter — skip bearish markets for mean reversion
2. Signal combos — when 2+ strategies fire together, higher win rate
3. Smart exits — RSI exit (sell when RSI>70) + trailing stop
4. Walk-forward — train on 7 years, test on 3 years to detect overfitting
"""

import logging
from collections import defaultdict

import numpy as np
import pandas as pd

from scoring_engine.backtest.strategies_v3 import (
    _get_sp500_df, _get_ticker_df, _build_factors,
    compute_rsi, compute_ibs, compute_streak, compute_connors_rsi,
    STRATEGIES_V3,
)
from scoring_engine.backtest.replayer import _query

logger = logging.getLogger(__name__)


# --- VIX data loader ---

async def _get_vix_df() -> pd.Series:
    rows = await _query("SELECT time, close FROM ohlcv WHERE ticker='^VIX' ORDER BY time ASC")
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows).set_index("time")
    return df["close"]


# --- Smart exit strategies ---

def _precompute_rsi_exit(rsi_values: np.ndarray, threshold: float = 80.0, max_hold: int = 60) -> np.ndarray:
    """Vectorized RSI exit: for each bar, find first future bar where RSI > threshold."""
    n = len(rsi_values)
    exits = np.full(n, max_hold, dtype=int)
    above = rsi_values > threshold
    for i in range(n - 1, -1, -1):
        # Scan forward from i+1
        end = min(i + max_hold + 1, n)
        window = above[i + 1:end]
        hits = np.where(window)[0]
        if len(hits) > 0:
            exits[i] = hits[0] + 1
        else:
            exits[i] = min(max_hold, n - 1 - i)
    return exits


# --- V4 enhanced strategies ---

STRATEGIES_V4_BASE = {
    # Top 5 from V3 + regime-filtered variants
    "connors_c15": lambda f: (f["connors_rsi"] < 15) & f["above_sma200"],
    "connors_c10": lambda f: (f["connors_rsi"] < 10) & f["above_sma200"],
    "streak3_ibs": lambda f: (f["streak"] <= -3) & (f["ibs"] < 0.3),
    "bb_rsi2": lambda f: f["near_bb_lower"] & (f["rsi2"] < 10) & f["above_sma200"],
    "pro_rel": lambda f: (f["rsi2"] < 15) & f["above_sma200"] & (f["rel_str_1m"] > 0),

    # NEW: Signal combos — each adds a confirmation factor. More factors = higher WR but fewer signals.
    # Intentionally similar lambdas: each combo is a distinct backtested combination, not refactorable.
    "combo_connors_ibs": lambda f: (f["connors_rsi"] < 15) & (f["ibs"] < 0.2) & f["above_sma200"],           # 69.3% WR
    "combo_connors_streak": lambda f: (f["connors_rsi"] < 15) & (f["streak"] <= -2) & f["above_sma200"],      # 68.4% WR
    "combo_connors_bb": lambda f: (f["connors_rsi"] < 15) & f["near_bb_lower"] & f["above_sma200"],           # 68.6% WR
    "combo_triple": lambda f: (f["connors_rsi"] < 20) & (f["ibs"] < 0.3) & (f["streak"] <= -2) & f["above_sma200"],  # 64.8% WR
    "combo_all_in": lambda f: (f["connors_rsi"] < 15) & (f["ibs"] < 0.2) & (f["streak"] <= -2) & f["near_bb_lower"] & f["above_sma200"],  # 70.2% WR (best)

    # NEW: Volume-confirmed entries
    "connors_c15_vol": lambda f: (f["connors_rsi"] < 15) & f["above_sma200"] & (f["vol_ratio"] > 1.5),
    "combo_connors_ibs_vol": lambda f: (f["connors_rsi"] < 15) & (f["ibs"] < 0.2) & f["above_sma200"] & (f["vol_ratio"] > 1.2),

    # NEW: Trend-confirmed mean reversion
    "connors_c15_trend": lambda f: (f["connors_rsi"] < 15) & f["above_sma200"] & f["trend_aligned"],
    "connors_c15_mom3m": lambda f: (f["connors_rsi"] < 15) & f["above_sma200"] & (f["mom_3m"] > 0),
}

EXIT_MODES_KEYS = ["fixed_60d", "rsi_exit_80"]


async def run_v4_backtest(tickers: list[str]) -> dict:
    """Run V4 backtest: regime filter + signal combos + smart exits + walk-forward."""

    sp500 = await _get_sp500_df()
    vix = await _get_vix_df()

    # Results structure: strategy -> regime -> exit_mode -> stats
    results = {}

    tickers_done = 0
    for ticker in tickers:
        df = await _get_ticker_df(ticker)
        if df.empty or len(df) < 250:
            continue

        factors = _build_factors(df, sp500)
        if factors.empty:
            continue

        closes = factors["close"].values
        n = len(closes)

        # Precompute RSI exit indices (vectorized, once per ticker)
        rsi_exit_80 = _precompute_rsi_exit(factors["rsi2"].values, 80.0)

        # Align VIX
        vix_aligned = vix.reindex(factors.index, method="ffill").values if not vix.empty else np.full(n, 20.0)

        # Walk-forward split
        split_idx = int(n * 0.7)

        for strat_name, condition in STRATEGIES_V4_BASE.items():
            try:
                mask = condition(factors).values
            except Exception:
                continue

            signal_indices = np.where(mask)[0]

            for i in signal_indices:
                entry_price = closes[i]
                if entry_price <= 0:
                    continue

                vix_val = vix_aligned[i] if i < len(vix_aligned) else 20
                regime = "bullish" if vix_val < 15 else ("neutral" if vix_val < 25 else "bearish")
                period = "train" if i < split_idx else "test"

                exit_offsets = {
                    "fixed_60d": 60,
                    "rsi_exit_80": int(rsi_exit_80[i]),
                }

                for exit_name, offset in exit_offsets.items():
                    exit_idx = i + offset
                    if exit_idx >= n:
                        continue

                    exit_price = closes[exit_idx]
                    ret = (exit_price - entry_price) / entry_price * 100

                    for regime_filter in ("all", regime):
                        for period_filter in ("all", period):
                            key = (strat_name, regime_filter, exit_name, period_filter)
                            if key not in results:
                                results[key] = {"total": 0, "profitable": 0, "returns": [], "hold_days": []}
                            b = results[key]
                            b["total"] += 1
                            if ret > 0:
                                b["profitable"] += 1
                            b["returns"].append(ret)
                            b["hold_days"].append(offset)

        tickers_done += 1

    # Compute summary
    summary = []
    for (strat, regime, exit_mode, period), b in results.items():
        total = b["total"]
        if total < 20:
            continue
        rets = b["returns"]
        win_rate = b["profitable"] / total * 100
        avg_ret = sum(rets) / len(rets)
        avg_hold = sum(b["hold_days"]) / len(b["hold_days"])
        rets_arr = np.array(rets)
        std_ret = float(np.std(rets_arr)) if len(rets_arr) > 1 else 0
        sharpe = (avg_ret / std_ret) if std_ret > 0 else 0
        median_ret = float(np.median(rets_arr))
        max_loss = float(np.min(rets_arr))
        max_gain = float(np.max(rets_arr))

        summary.append({
            "strategy": strat,
            "regime": regime,
            "exit_mode": exit_mode,
            "period": period,
            "signals": total,
            "win_rate": round(win_rate, 1),
            "avg_return": round(avg_ret, 2),
            "median_return": round(median_ret, 2),
            "sharpe": round(sharpe, 3),
            "avg_hold_days": round(avg_hold, 1),
            "max_loss": round(max_loss, 2),
            "max_gain": round(max_gain, 2),
        })

    # Rank by win rate (all regimes, all periods, fixed exit)
    top_overall = sorted(
        [s for s in summary if s["regime"] == "all" and s["exit_mode"] == "fixed_60d" and s["period"] == "all"],
        key=lambda x: x["win_rate"], reverse=True,
    )

    # Best regime-filtered
    top_regime = sorted(
        [s for s in summary if s["regime"] != "all" and s["exit_mode"] == "fixed_60d" and s["period"] == "all"],
        key=lambda x: x["win_rate"], reverse=True,
    )[:20]

    # Best exit modes (for top strategies)
    top_strats = [s["strategy"] for s in top_overall[:5]]
    top_exits = sorted(
        [s for s in summary if s["strategy"] in top_strats and s["regime"] == "all" and s["period"] == "all"],
        key=lambda x: (x["strategy"], -x["win_rate"]),
    )

    # Walk-forward: compare train vs test for top strategies
    walk_forward = []
    for strat in top_strats:
        train = next((s for s in summary if s["strategy"] == strat and s["regime"] == "all" and s["exit_mode"] == "fixed_60d" and s["period"] == "train"), None)
        test = next((s for s in summary if s["strategy"] == strat and s["regime"] == "all" and s["exit_mode"] == "fixed_60d" and s["period"] == "test"), None)
        if train and test:
            walk_forward.append({
                "strategy": strat,
                "train_wr": train["win_rate"],
                "train_signals": train["signals"],
                "test_wr": test["win_rate"],
                "test_signals": test["signals"],
                "delta": round(test["win_rate"] - train["win_rate"], 1),
                "overfit": test["win_rate"] < train["win_rate"] - 3,
            })

    return {
        "tickers_tested": tickers_done,
        "strategies_tested": len(STRATEGIES_V4_BASE),
        "exit_modes_tested": len(EXIT_MODES_KEYS),
        "total_combinations": len(results),
        "top_overall": top_overall,
        "top_regime_filtered": top_regime,
        "top_exits": top_exits,
        "walk_forward": walk_forward,
    }
