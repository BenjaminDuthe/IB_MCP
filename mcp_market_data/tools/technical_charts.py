"""Technical analysis charts — candlestick with RSI, MACD, Bollinger overlays."""

import asyncio
import base64
import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplfinance as mpf
import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from starlette.responses import StreamingResponse

from mcp_market_data.tools._ticker_pool import get_ticker

router = APIRouter(prefix="/charts", tags=["Technical Charts"])

CHART_STYLE = mpf.make_mpf_style(
    base_mpf_style="charles",
    marketcolors=mpf.make_marketcolors(up="#00c853", down="#ff1744", inherit=True),
    figcolor="white",
    gridstyle="--",
    gridcolor="#e0e0e0",
)


def _chart_response(buf: io.BytesIO, fmt: str, filename: str):
    if fmt == "base64":
        b64 = base64.b64encode(buf.read()).decode("ascii")
        return {"image_base64": b64, "filename": filename, "media_type": "image/png"}
    return StreamingResponse(buf, media_type="image/png")


def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _compute_macd(close: pd.Series):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _generate_technical_chart(ticker: str, period: str) -> io.BytesIO:
    t = get_ticker(ticker)
    hist = t.history(period=period)
    if hist.empty:
        raise ValueError(f"No data for {ticker}")

    hist.index = pd.to_datetime(hist.index)
    if hist.index.tz is not None:
        hist.index = hist.index.tz_localize(None)

    close = hist["Close"]
    info = t.info
    name = info.get("shortName", ticker)

    # Bollinger Bands
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_upper = sma20 + 2 * std20
    bb_lower = sma20 - 2 * std20

    # Moving averages for price panel
    add_plots = []

    # Bollinger Bands (filled area)
    add_plots.append(mpf.make_addplot(bb_upper, color="#2196f3", width=0.8, linestyle="--", panel=0))
    add_plots.append(mpf.make_addplot(bb_lower, color="#2196f3", width=0.8, linestyle="--", panel=0))
    add_plots.append(mpf.make_addplot(sma20, color="#2196f3", width=0.8, panel=0))

    # SMA 50 / 200 if enough data
    if len(close) >= 50:
        sma50 = close.rolling(50).mean()
        add_plots.append(mpf.make_addplot(sma50, color="#ff9800", width=1.0, panel=0))
    if len(close) >= 200:
        sma200 = close.rolling(200).mean()
        add_plots.append(mpf.make_addplot(sma200, color="#9c27b0", width=1.0, panel=0))

    # RSI panel (panel 2, after volume panel 1)
    rsi = _compute_rsi(close)
    add_plots.append(mpf.make_addplot(rsi, panel=2, color="#ff9800", width=1.2, ylabel="RSI"))

    # RSI 30/70 reference lines
    rsi_30 = pd.Series(30, index=hist.index)
    rsi_70 = pd.Series(70, index=hist.index)
    add_plots.append(mpf.make_addplot(rsi_30, panel=2, color="#4caf50", width=0.5, linestyle="--"))
    add_plots.append(mpf.make_addplot(rsi_70, panel=2, color="#f44336", width=0.5, linestyle="--"))

    # MACD panel (panel 3)
    macd_line, signal_line, histogram = _compute_macd(close)
    colors = ["#00c853" if v >= 0 else "#ff1744" for v in histogram]
    add_plots.append(mpf.make_addplot(macd_line, panel=3, color="#2196f3", width=1.0, ylabel="MACD"))
    add_plots.append(mpf.make_addplot(signal_line, panel=3, color="#ff9800", width=0.8))
    add_plots.append(mpf.make_addplot(histogram, panel=3, type="bar", color=colors, width=0.7))

    buf = io.BytesIO()
    fig, axes = mpf.plot(
        hist,
        type="candle",
        style=CHART_STYLE,
        title=f"\n{name} ({ticker}) — Technical Analysis ({period})",
        ylabel="Price ($)",
        ylabel_lower="Volume",
        volume=True,
        addplot=add_plots,
        figsize=(12, 10),
        panel_ratios=(4, 1, 1.5, 1.5),
        returnfig=True,
        tight_layout=True,
    )

    # Annotate last price
    last_close = float(close.iloc[-1])
    prev_close = float(close.iloc[-2]) if len(close) > 1 else last_close
    change_pct = ((last_close - prev_close) / prev_close) * 100
    color = "#00c853" if change_pct >= 0 else "#ff1744"
    sign = "+" if change_pct >= 0 else ""
    axes[0].annotate(
        f"${last_close:.2f} ({sign}{change_pct:.1f}%)",
        xy=(1.0, last_close), xycoords=("axes fraction", "data"),
        fontsize=10, fontweight="bold", color=color, ha="right", va="bottom",
    )

    # RSI annotation
    rsi_val = float(rsi.iloc[-1])
    if not np.isnan(rsi_val):
        rsi_color = "#f44336" if rsi_val >= 70 else ("#4caf50" if rsi_val <= 30 else "#ff9800")
        axes[4].annotate(
            f"RSI: {rsi_val:.1f}",
            xy=(1.0, rsi_val), xycoords=("axes fraction", "data"),
            fontsize=9, fontweight="bold", color=rsi_color, ha="right", va="bottom",
        )

    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


@router.get("/technicals/{ticker}")
async def chart_technicals(
    ticker: str,
    period: str = Query("6mo", description="Period: 3mo,6mo,1y"),
    format: str = Query("png", description="Output: png (image) or base64 (JSON with encoded image)"),
):
    """Generate a technical analysis chart with candlestick, Bollinger Bands, RSI, and MACD panels. Returns PNG image or base64 JSON."""
    try:
        buf = await asyncio.to_thread(_generate_technical_chart, ticker.upper(), period)
        return _chart_response(buf, format, f"technicals_{ticker.upper()}_{period}.png")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating chart for {ticker}: {e}")
