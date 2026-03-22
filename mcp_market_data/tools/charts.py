import asyncio
import base64
import io
import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

import mplfinance as mpf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd

from mcp_market_data.tools._ticker_pool import get_ticker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/charts", tags=["Charts"])

# Shared style for all charts
CHART_STYLE = mpf.make_mpf_style(
    base_mpf_style="yahoo",
    rc={"font.size": 9},
)


def _generate_candlestick(ticker: str, period: str, interval: str) -> io.BytesIO:
    """Generate a candlestick chart with volume and moving averages."""
    t = get_ticker(ticker)
    hist = t.history(period=period, interval=interval)
    if hist.empty:
        raise ValueError(f"No data for {ticker}")

    hist.index = pd.to_datetime(hist.index)
    if hist.index.tz is not None:
        hist.index = hist.index.tz_localize(None)

    info = t.info
    name = info.get("shortName", ticker)

    mavs = ()
    if len(hist) >= 50:
        mavs = (20, 50)
    elif len(hist) >= 20:
        mavs = (20,)

    buf = io.BytesIO()
    fig, axes = mpf.plot(
        hist,
        type="candle",
        style=CHART_STYLE,
        title=f"\n{name} ({ticker}) — {period}",
        ylabel="Price ($)",
        ylabel_lower="Volume",
        volume=True,
        mav=mavs,
        figsize=(10, 6),
        returnfig=True,
        tight_layout=True,
    )

    # Add last price annotation
    last_close = hist["Close"].iloc[-1]
    prev_close = hist["Close"].iloc[-2] if len(hist) > 1 else last_close
    change_pct = ((last_close - prev_close) / prev_close) * 100
    color = "#00c853" if change_pct >= 0 else "#ff1744"
    sign = "+" if change_pct >= 0 else ""

    axes[0].annotate(
        f"${last_close:.2f} ({sign}{change_pct:.1f}%)",
        xy=(1.0, last_close),
        xycoords=("axes fraction", "data"),
        fontsize=11,
        fontweight="bold",
        color=color,
        ha="right",
        va="bottom",
    )

    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _generate_comparison(tickers: list[str], period: str) -> io.BytesIO:
    """Generate a normalized comparison chart for multiple tickers."""
    fig, ax = plt.subplots(figsize=(10, 5))

    colors = ["#2196F3", "#FF5722", "#4CAF50", "#9C27B0", "#FF9800", "#00BCD4", "#E91E63", "#795548"]

    for i, ticker in enumerate(tickers):
        try:
            t = get_ticker(ticker)
            hist = t.history(period=period)
            if hist.empty:
                continue
            normalized = (hist["Close"] / hist["Close"].iloc[0] - 1) * 100
            color = colors[i % len(colors)]
            ax.plot(normalized.index, normalized.values, label=ticker, color=color, linewidth=1.8)
        except Exception:
            continue

    ax.set_title(f"Performance comparee — {period}", fontsize=13, fontweight="bold")
    ax.set_ylabel("Variation (%)", fontsize=10)
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.axhline(y=0, color="gray", linewidth=0.8, linestyle="--")

    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%+.0f%%"))

    fig.autofmt_xdate()
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _generate_fear_greed_gauge(score: float) -> io.BytesIO:
    """Generate a Fear & Greed gauge chart."""
    fig, ax = plt.subplots(figsize=(6, 3.5))

    import numpy as np

    # Draw gauge arc
    theta = np.linspace(np.pi, 0, 100)
    r = 1.0

    # Color segments: Extreme Fear, Fear, Neutral, Greed, Extreme Greed
    segments = [
        (0, 25, "#d32f2f"),
        (25, 45, "#ff9800"),
        (45, 55, "#fdd835"),
        (55, 75, "#8bc34a"),
        (75, 100, "#2e7d32"),
    ]

    for start, end, color in segments:
        t_start = np.pi - (start / 100) * np.pi
        t_end = np.pi - (end / 100) * np.pi
        t = np.linspace(t_start, t_end, 30)
        for width in [0.85, 0.90, 0.95, 1.0, 1.05, 1.10, 1.15]:
            ax.plot(width * np.cos(t), width * np.sin(t), color=color, linewidth=3, solid_capstyle="butt")

    # Needle
    needle_angle = np.pi - (score / 100) * np.pi
    ax.plot(
        [0, 0.75 * np.cos(needle_angle)],
        [0, 0.75 * np.sin(needle_angle)],
        color="black", linewidth=2.5, solid_capstyle="round",
    )
    ax.plot(0, 0, "ko", markersize=6)

    # Labels
    labels = {
        "Extreme\nFear": 12.5,
        "Fear": 35,
        "Neutral": 50,
        "Greed": 65,
        "Extreme\nGreed": 87.5,
    }
    for label, pos in labels.items():
        angle = np.pi - (pos / 100) * np.pi
        ax.text(
            1.35 * np.cos(angle), 1.35 * np.sin(angle),
            label, ha="center", va="center", fontsize=7, color="#555",
        )

    # Score display
    if score <= 24:
        label = "Extreme Fear"
        color = "#d32f2f"
    elif score <= 44:
        label = "Fear"
        color = "#ff9800"
    elif score <= 55:
        label = "Neutral"
        color = "#fdd835"
    elif score <= 74:
        label = "Greed"
        color = "#8bc34a"
    else:
        label = "Extreme Greed"
        color = "#2e7d32"

    ax.text(0, -0.25, f"{score:.0f}", ha="center", va="center", fontsize=28, fontweight="bold", color=color)
    ax.text(0, -0.5, label, ha="center", va="center", fontsize=12, color=color)
    ax.text(0, -0.7, f"CNN Fear & Greed Index", ha="center", va="center", fontsize=8, color="#999")

    ax.set_xlim(-1.7, 1.7)
    ax.set_ylim(-0.85, 1.55)
    ax.set_aspect("equal")
    ax.axis("off")

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _chart_response(buf: io.BytesIO, fmt: str, filename: str):
    """Return chart as PNG stream or base64 JSON depending on format."""
    if fmt == "base64":
        b64 = base64.b64encode(buf.read()).decode("ascii")
        return {"image_base64": b64, "filename": filename, "media_type": "image/png"}
    return StreamingResponse(buf, media_type="image/png")


@router.get("/price/{ticker}")
async def chart_price(
    ticker: str,
    period: str = Query("6mo", description="Period: 1mo,3mo,6mo,1y,2y,5y"),
    interval: str = Query("1d", description="Interval: 1d,1wk"),
    format: str = Query("png", description="Output: png (image) or base64 (JSON with encoded image)"),
):
    """Generate a candlestick chart with volume and moving averages. Returns PNG image or base64 JSON."""
    try:
        buf = await asyncio.to_thread(_generate_candlestick, ticker.upper(), period, interval)
        return _chart_response(buf, format, f"chart_{ticker.upper()}_{period}.png")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Chart error for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/comparison")
async def chart_comparison(
    tickers: str = Query(..., description="Comma-separated tickers: AAPL,MSFT,GOOGL"),
    period: str = Query("6mo", description="Period: 1mo,3mo,6mo,1y,2y"),
    format: str = Query("png", description="Output: png (image) or base64 (JSON with encoded image)"),
):
    """Generate a normalized performance comparison chart. Returns PNG image or base64 JSON."""
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if len(ticker_list) < 2:
        raise HTTPException(status_code=400, detail="At least 2 tickers required")
    if len(ticker_list) > 8:
        raise HTTPException(status_code=400, detail="Maximum 8 tickers")
    try:
        buf = await asyncio.to_thread(_generate_comparison, ticker_list, period)
        return _chart_response(buf, format, f"comparison_{period}.png")
    except Exception as e:
        logger.error(f"Comparison chart error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/feargreed")
async def chart_fear_greed(
    score: float = Query(..., ge=0, le=100, description="Fear & Greed score (0-100)"),
    format: str = Query("png", description="Output: png (image) or base64 (JSON with encoded image)"),
):
    """Generate a Fear & Greed gauge chart. Returns PNG image or base64 JSON."""
    try:
        buf = await asyncio.to_thread(_generate_fear_greed_gauge, score)
        return _chart_response(buf, format, f"feargreed_{int(score)}.png")
    except Exception as e:
        logger.error(f"Fear & Greed chart error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
