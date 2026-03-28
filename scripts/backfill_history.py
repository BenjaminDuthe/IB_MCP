#!/usr/bin/env python3
"""Backfill 10 years of historical OHLCV + technicals into InfluxDB.

Usage:
    python scripts/backfill_history.py --tickers all --years 10
    python scripts/backfill_history.py --tickers macro --years 10
    python scripts/backfill_history.py --tickers NVDA,MSFT --years 5 --dry-run
"""

import argparse
import asyncio
import os
import logging
import sys
import time
from datetime import datetime

import httpx
import numpy as np
import pandas as pd
import yfinance as yf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# --- Configuration ---

INFLUXDB_URL = os.environ.get("INFLUXDB_URL", "http://192.168.1.123:8086")
INFLUXDB_DB = os.environ.get("INFLUXDB_DATABASE", "trading")
INFLUXDB_USER = os.environ.get("INFLUXDB_USER", "trading_writer")
INFLUXDB_PASSWORD = os.environ.get("INFLUXDB_PASSWORD", "")

WATCHLIST = {
    "NVDA": "US", "MSFT": "US", "GOOGL": "US", "AMZN": "US",
    "META": "US", "AAPL": "US", "NFLX": "US",
    "MC.PA": "FR", "SU.PA": "FR", "AIR.PA": "FR",
    "BNP.PA": "FR", "SAF.PA": "FR", "TTE.PA": "FR",
}

MACRO_SYMBOLS = {
    "^GSPC": "MACRO", "^VIX": "MACRO", "^TNX": "MACRO",
    "DX-Y.NYB": "MACRO", "GC=F": "MACRO", "CL=F": "MACRO",
    "BTC-USD": "MACRO", "^DJI": "MACRO", "^IXIC": "MACRO",
    "^RUT": "MACRO", "^FVX": "MACRO",
}

SEMAPHORE = asyncio.Semaphore(3)
BATCH_DELAY = 2.0  # seconds between batches


# --- Technical indicator calculations (from technicals.py) ---

def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def compute_macd(close: pd.Series) -> pd.DataFrame:
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal
    return pd.DataFrame({"macd": macd_line, "signal": signal, "histogram": histogram})


def compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period).mean()


def compute_bollinger(close: pd.Series, period: int = 20) -> pd.DataFrame:
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    return pd.DataFrame({
        "upper": sma + 2 * std,
        "lower": sma - 2 * std,
    })


def compute_stochastic(high: pd.Series, low: pd.Series, close: pd.Series, k_period: int = 14) -> pd.Series:
    lowest = low.rolling(k_period).min()
    highest = high.rolling(k_period).max()
    return 100 * (close - lowest) / (highest - lowest)


def compute_all_technicals(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all technicals from OHLCV DataFrame."""
    close = df["Close"]
    high = df["High"]
    low = df["Low"]

    result = pd.DataFrame(index=df.index)
    result["rsi_14"] = compute_rsi(close)
    macd = compute_macd(close)
    result["macd_histogram"] = macd["histogram"]
    result["sma_20"] = close.rolling(20).mean()
    result["sma_50"] = close.rolling(50).mean()
    result["sma_200"] = close.rolling(200).mean()
    result["atr_14"] = compute_atr(high, low, close)
    boll = compute_bollinger(close)
    result["bollinger_upper"] = boll["upper"]
    result["bollinger_lower"] = boll["lower"]
    result["stochastic_k"] = compute_stochastic(high, low, close)
    return result


# --- InfluxDB writer ---

def escape_tag(v: str) -> str:
    return v.replace(" ", "\\ ").replace(",", "\\,").replace("=", "\\=")


async def write_influx(lines: list[str], client: httpx.AsyncClient) -> bool:
    if not lines:
        return True
    body = "\n".join(lines)
    params = {"db": INFLUXDB_DB, "precision": "s", "u": INFLUXDB_USER, "p": INFLUXDB_PASSWORD}
    try:
        resp = await client.post(f"{INFLUXDB_URL}/write", params=params, content=body)
        if resp.status_code == 204:
            return True
        logger.error("InfluxDB write error %d: %s", resp.status_code, resp.text[:200])
        return False
    except Exception as e:
        logger.error("InfluxDB write failed: %s", e)
        return False


# --- Download + ingest ---

async def backfill_ticker(
    ticker: str, market: str, years: int,
    client: httpx.AsyncClient, dry_run: bool = False,
) -> dict:
    """Download and ingest historical data for one ticker."""
    async with SEMAPHORE:
        logger.info("Downloading %s (%s) — %d years...", ticker, market, years)
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period=f"{years}y", interval="1d")
        except Exception as e:
            logger.error("yfinance failed for %s: %s", ticker, e)
            return {"ticker": ticker, "error": str(e), "ohlcv": 0, "technicals": 0}

        if hist.empty:
            logger.warning("No data for %s", ticker)
            return {"ticker": ticker, "error": "no_data", "ohlcv": 0, "technicals": 0}

        logger.info("  %s: %d bars (%s → %s)", ticker, len(hist),
                     hist.index[0].strftime("%Y-%m-%d"), hist.index[-1].strftime("%Y-%m-%d"))

        # --- OHLCV lines ---
        ohlcv_lines = []
        for idx, row in hist.iterrows():
            ts = int(idx.timestamp())
            fields = []
            for col in ["Open", "High", "Low", "Close", "Volume"]:
                v = row.get(col)
                if v is not None and not np.isnan(v):
                    if col == "Volume":
                        fields.append(f"{col.lower()}={int(v)}i")
                    else:
                        fields.append(f"{col.lower()}={round(v, 4)}")
            if fields:
                ohlcv_lines.append(
                    f"ohlcv,ticker={escape_tag(ticker)},market={market} {','.join(fields)} {ts}"
                )

        # --- Technicals lines ---
        tech = compute_all_technicals(hist)
        tech_lines = []
        for idx, row in tech.iterrows():
            ts = int(idx.timestamp())
            fields = []
            for col in tech.columns:
                v = row[col]
                if v is not None and not np.isnan(v):
                    fields.append(f"{col}={round(v, 4)}")
            if fields:
                tech_lines.append(
                    f"technicals_history,ticker={escape_tag(ticker)},market={market} {','.join(fields)} {ts}"
                )

        if dry_run:
            logger.info("  [DRY-RUN] %s: %d OHLCV + %d technicals points",
                        ticker, len(ohlcv_lines), len(tech_lines))
            return {"ticker": ticker, "ohlcv": len(ohlcv_lines), "technicals": len(tech_lines)}

        # Write in batches of 5000 lines
        batch_size = 5000
        ohlcv_ok = True
        for i in range(0, len(ohlcv_lines), batch_size):
            ok = await write_influx(ohlcv_lines[i:i + batch_size], client)
            if not ok:
                ohlcv_ok = False

        tech_ok = True
        for i in range(0, len(tech_lines), batch_size):
            ok = await write_influx(tech_lines[i:i + batch_size], client)
            if not ok:
                tech_ok = False

        status = "OK" if (ohlcv_ok and tech_ok) else "PARTIAL"
        logger.info("  %s: %s — %d OHLCV + %d technicals written",
                     ticker, status, len(ohlcv_lines), len(tech_lines))

        return {"ticker": ticker, "ohlcv": len(ohlcv_lines), "technicals": len(tech_lines)}


async def backfill_fundamentals(
    ticker: str, client: httpx.AsyncClient, dry_run: bool = False,
) -> dict:
    """Download quarterly fundamentals (limited to 4-8 quarters by yfinance)."""
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
    except Exception as e:
        logger.error("Fundamentals failed for %s: %s", ticker, e)
        return {"ticker": ticker, "fundamentals": 0}

    fields = []
    for key, influx_key in [
        ("forwardPE", "forward_pe"), ("trailingPE", "trailing_pe"),
        ("revenueGrowth", "revenue_growth"), ("profitMargins", "profit_margin"),
        ("debtToEquity", "debt_to_equity"), ("returnOnEquity", "roe"),
        ("beta", "beta"), ("dividendYield", "dividend_yield"),
    ]:
        v = info.get(key)
        if v is not None:
            fields.append(f"{influx_key}={round(float(v), 4)}")

    if not fields:
        return {"ticker": ticker, "fundamentals": 0}

    ts = int(time.time())
    market = WATCHLIST.get(ticker, "US")
    line = f"fundamentals,ticker={escape_tag(ticker)},market={market} {','.join(fields)} {ts}"

    if dry_run:
        logger.info("  [DRY-RUN] %s: 1 fundamentals point (%d fields)", ticker, len(fields))
        return {"ticker": ticker, "fundamentals": 1}

    ok = await write_influx([line], client)
    return {"ticker": ticker, "fundamentals": 1 if ok else 0}


async def main(tickers_mode: str, years: int, dry_run: bool):
    start = time.time()

    # Build ticker list
    if tickers_mode == "all":
        symbols = {**WATCHLIST, **MACRO_SYMBOLS}
    elif tickers_mode == "macro":
        symbols = MACRO_SYMBOLS
    elif tickers_mode == "stocks":
        symbols = WATCHLIST
    else:
        # Comma-separated list
        symbols = {t.strip(): WATCHLIST.get(t.strip(), MACRO_SYMBOLS.get(t.strip(), "US"))
                   for t in tickers_mode.split(",")}

    logger.info("=== BACKFILL %d YEARS — %d symbols — %s ===",
                years, len(symbols), "DRY-RUN" if dry_run else "LIVE")

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Phase 1: OHLCV + Technicals
        tasks = [
            backfill_ticker(ticker, market, years, client, dry_run)
            for ticker, market in symbols.items()
        ]
        # Process in batches of 3 (semaphore handles concurrency)
        results = await asyncio.gather(*tasks)

        total_ohlcv = sum(r["ohlcv"] for r in results)
        total_tech = sum(r["technicals"] for r in results)
        errors = [r for r in results if r.get("error")]

        # Phase 2: Fundamentals (stocks only)
        fund_results = []
        stock_tickers = [t for t, m in symbols.items() if m in ("US", "FR")]
        if stock_tickers:
            fund_tasks = [backfill_fundamentals(t, client, dry_run) for t in stock_tickers]
            fund_results = await asyncio.gather(*fund_tasks)

        total_fund = sum(r["fundamentals"] for r in fund_results)

    duration = time.time() - start
    logger.info("=== DONE in %.1fs ===", duration)
    logger.info("  OHLCV points: %d", total_ohlcv)
    logger.info("  Technicals points: %d", total_tech)
    logger.info("  Fundamentals points: %d", total_fund)
    logger.info("  Errors: %d (%s)", len(errors), ", ".join(r["ticker"] for r in errors))

    return {"ohlcv": total_ohlcv, "technicals": total_tech, "fundamentals": total_fund,
            "errors": len(errors), "duration": round(duration, 1)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill historical trading data into InfluxDB")
    parser.add_argument("--tickers", default="all", help="all|stocks|macro|NVDA,MSFT,...")
    parser.add_argument("--years", type=int, default=10, help="Years of history (default: 10)")
    parser.add_argument("--dry-run", action="store_true", help="Download but don't write to InfluxDB")
    args = parser.parse_args()

    asyncio.run(main(args.tickers, args.years, args.dry_run))
