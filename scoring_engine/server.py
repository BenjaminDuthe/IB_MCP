"""FastAPI server with APScheduler for the scoring engine."""

import logging
from contextlib import asynccontextmanager
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI

from scoring_engine.config import WATCHLIST, TZ_CET, AGENT_LAYERS_ENABLED, DEBATE_ENABLED, RISK_SIZING_ENABLED, FEEDBACK_ENABLED
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

async def job_scan_eu():
    logger.info("Scheduled: EU market scan")
    await scan_market("FR")


async def job_scan_us():
    logger.info("Scheduled: US market scan")
    await scan_market("US")


async def job_daily_summary():
    logger.info("Scheduled: daily summary")
    await generate_daily_summary()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # EU market: Mon-Fri 9:00-17:30 CET, every 30min
    scheduler.add_job(
        job_scan_eu, CronTrigger(
            day_of_week="mon-fri", hour="9-17", minute="0,30",
            timezone="Europe/Paris",
        ),
        id="scan_eu",
    )
    # US market: Mon-Fri 15:30-22:00 CET, every 30min
    scheduler.add_job(
        job_scan_us, CronTrigger(
            day_of_week="mon-fri", hour="15-21", minute="0,30",
            timezone="Europe/Paris",
        ),
        id="scan_us",
    )
    # Daily summary: Mon-Fri 22:30 CET
    scheduler.add_job(
        job_daily_summary, CronTrigger(
            day_of_week="mon-fri", hour=22, minute=30,
            timezone="Europe/Paris",
        ),
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
            "debate": DEBATE_ENABLED,
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
    """Full analysis with debate forced ON (manual trigger only)."""
    ticker = ticker.upper()
    return await scan_ticker(ticker, force_debate=True)


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
