"""FastAPI server with APScheduler for the scoring engine."""

import logging
from contextlib import asynccontextmanager
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI

from scoring_engine.config import WATCHLIST, TZ_CET, AGENT_LAYERS_ENABLED, RISK_SIZING_ENABLED, FEEDBACK_ENABLED
from scoring_engine.pipeline import (
    scan_ticker,
    scan_market,
    get_top_signals,
    generate_daily_summary,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="Europe/Paris")


# --- Scheduled jobs ---

async def _scan_exchange(exchange: str):
    from scoring_engine.pipeline import scan_exchange
    logger.info("Scheduled: %s scan", exchange)
    await scan_exchange(exchange)


async def job_daily_summary():
    logger.info("Scheduled: daily summary")
    await generate_daily_summary()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # EU exchanges at open (Mon-Fri, CET)
    for exchange, minute in [("Paris", 0), ("Frankfurt", 5), ("Amsterdam", 10), ("Zurich", 15), ("London", 20)]:
        scheduler.add_job(
            _scan_exchange, CronTrigger(day_of_week="mon-fri", hour=9, minute=minute, timezone="Europe/Paris"),
            args=[exchange], id=f"scan_{exchange.lower()}",
        )
    # EU rescans at 12:00 and 16:00 CET
    for hour in [12, 16]:
        for exchange, minute in [("Paris", 0), ("Frankfurt", 5), ("Amsterdam", 10), ("Zurich", 15), ("London", 20)]:
            scheduler.add_job(
                _scan_exchange, CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute, timezone="Europe/Paris"),
                args=[exchange], id=f"scan_{exchange.lower()}_{hour}h",
            )
    # US exchanges (NYSE + NASDAQ) at open 15:30 CET, then 18:00, 20:30
    for hour, minute in [(15, 30), (18, 0), (20, 30)]:
        scheduler.add_job(
            _scan_exchange, CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute, timezone="Europe/Paris"),
            args=["NYSE"], id=f"scan_nyse_{hour}h{minute:02d}",
        )
        scheduler.add_job(
            _scan_exchange, CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute + 5, timezone="Europe/Paris"),
            args=["NASDAQ"], id=f"scan_nasdaq_{hour}h{minute + 5:02d}",
        )
    # Daily summary: Mon-Fri 22:30 CET
    scheduler.add_job(
        job_daily_summary, CronTrigger(day_of_week="mon-fri", hour=22, minute=30, timezone="Europe/Paris"),
        id="daily_summary",
    )
    # Weekly performance report: Friday 22:45 CET
    if FEEDBACK_ENABLED:
        async def job_weekly_perf():
            from scoring_engine.feedback.performance import generate_performance_report
            logger.info("Scheduled: weekly performance report")
            await generate_performance_report()

        async def job_drift_check():
            from scoring_engine.feedback.drift_detector import check_drift
            logger.info("Scheduled: drift check")
            await check_drift()

        scheduler.add_job(
            job_weekly_perf, CronTrigger(
                day_of_week="fri", hour=22, minute=45,
                timezone="Europe/Paris",
            ),
            id="weekly_perf",
        )
        scheduler.add_job(
            job_drift_check, CronTrigger(
                day_of_week="mon-fri", hour=23, minute=0,
                timezone="Europe/Paris",
            ),
            id="drift_check",
        )

    scheduler.start()
    logger.info("Scheduler started with %d jobs", len(scheduler.get_jobs()))
    yield
    scheduler.shutdown()


app = FastAPI(title="Scoring Engine", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "scheduler_running": scheduler.running,
        "jobs": len(scheduler.get_jobs()),
        "watchlist_size": len(WATCHLIST),
        "layers": {
            "agents": AGENT_LAYERS_ENABLED,
            "risk_sizing": RISK_SIZING_ENABLED,
            "feedback": FEEDBACK_ENABLED,
        },
        "timestamp": datetime.now(TZ_CET).isoformat(),
    }


@app.get("/api/scan/{ticker}")
async def api_scan_ticker(ticker: str):
    ticker = ticker.upper()
    return await scan_ticker(ticker)


@app.get("/api/analyze/{ticker}")
async def api_deep_analyze(ticker: str):
    """Single ticker analysis with OpenClaw decision."""
    ticker = ticker.upper()
    from scoring_engine.pipeline import scan_tickers
    result = await scan_tickers([ticker])
    if result["results"]:
        return result["results"][0]
    return {"error": "no_result"}


@app.get("/api/market-pulse")
async def api_market_pulse():
    """Scan all tickers, return summary."""
    results = {}
    for market in ("US", "FR"):
        results[market] = await scan_market(market)
    return results


@app.get("/api/top-signals")
async def api_top_signals(limit: int = 3):
    return await get_top_signals(limit)


@app.get("/api/weekly-summary")
async def api_weekly_summary():
    return await generate_daily_summary()


@app.get("/api/portfolio-check")
async def api_portfolio_check():
    """Simple portfolio-check placeholder — scans all tickers."""
    return await scan_market("US")


# --- Performance & Feedback endpoints ---

@app.get("/api/performance/weekly")
async def api_weekly_performance():
    from scoring_engine.feedback.performance import generate_weekly_performance
    return await generate_weekly_performance()


@app.get("/api/performance/signal-accuracy")
async def api_signal_accuracy():
    from scoring_engine.feedback.tracker import compute_signal_accuracy
    return await compute_signal_accuracy()


@app.get("/api/performance/drift")
async def api_drift_check():
    from scoring_engine.feedback.drift_detector import check_drift
    return await check_drift()


@app.get("/api/risk/portfolio")
async def api_portfolio_risk():
    """Get current risk state."""
    from scoring_engine.risk.portfolio_risk import get_active_signals, TICKER_SECTORS
    active = get_active_signals()
    sectors = {}
    for t in active:
        s = TICKER_SECTORS.get(t, "unknown")
        sectors[s] = sectors.get(s, 0) + 1
    return {"active_buy_signals": active, "sector_exposure": sectors}


# --- Backtesting endpoints ---

@app.post("/api/backtest/run")
async def api_run_backtest():
    """Run full backtest on 10 years of data for all 78 tickers. Takes ~2-5 min."""
    from scoring_engine.backtest.replayer import backtest_all
    from scoring_engine.backtest.calibration import save_calibration
    from scoring_engine.config import WATCHLIST

    params = {t: {"t5d_threshold": w["t5d_threshold"], "rsi_threshold": w["rsi_threshold"],
                   "require_sma200": w["require_sma200"]}
              for t, w in WATCHLIST.items()}

    result = await backtest_all(params, horizons=[5, 10, 20, 60])

    # Save calibration from global summary
    save_calibration(result["global_summary"])

    return result


@app.get("/api/backtest/calibration")
async def api_get_calibration():
    """Get current calibration table (win rates per score level)."""
    from scoring_engine.backtest.calibration import load_calibration
    return load_calibration()
