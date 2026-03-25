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

# Store pre-computed results for delivery at exact time
_pending_results: dict[str, dict] = {}


async def _prescan_exchanges(exchanges: list[str], delivery_label: str):
    """Scan exchanges in background BEFORE market open, store results."""
    from scoring_engine.pipeline import scan_exchange
    for exchange in exchanges:
        logger.info("Pre-scanning %s for %s delivery", exchange, delivery_label)
        result = await scan_exchange(exchange, send_discord=False)
        _pending_results[f"{delivery_label}:{exchange}"] = result


async def _deliver_results(exchanges: list[str], delivery_label: str):
    """Send stored results to Discord at exact delivery time."""
    from scoring_engine.alerter import alert_scan_summary
    for exchange in exchanges:
        key = f"{delivery_label}:{exchange}"
        result = _pending_results.pop(key, None)
        if result and result.get("results"):
            logger.info("Delivering %s scan to Discord NOW", exchange)
            await alert_scan_summary(exchange, result["results"], result.get("openclaw_verdicts"))
        else:
            logger.warning("No pre-scanned results for %s", exchange)


async def _scan_and_send(exchange: str):
    """Scan + send immediately (for rescans during the day)."""
    from scoring_engine.pipeline import scan_exchange
    logger.info("Scheduled: %s scan", exchange)
    await scan_exchange(exchange)


async def job_daily_summary():
    logger.info("Scheduled: daily summary")
    await generate_daily_summary()


EU_EXCHANGES = ["Paris", "Frankfurt", "Amsterdam", "Zurich", "London"]
US_EXCHANGES = ["NYSE", "NASDAQ"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- EU: pre-scan at 8:45, deliver at 9:00 ---
    scheduler.add_job(
        _prescan_exchanges, CronTrigger(day_of_week="mon-fri", hour=8, minute=45, timezone="Europe/Paris"),
        args=[EU_EXCHANGES, "9h"], id="prescan_eu_9h",
    )
    scheduler.add_job(
        _deliver_results, CronTrigger(day_of_week="mon-fri", hour=9, minute=0, timezone="Europe/Paris"),
        args=[EU_EXCHANGES, "9h"], id="deliver_eu_9h",
    )

    # --- EU rescans at 12:00 and 16:00 (scan + send immediately) ---
    for hour in [12, 16]:
        for exchange in EU_EXCHANGES:
            scheduler.add_job(
                _scan_and_send, CronTrigger(day_of_week="mon-fri", hour=hour, minute=0, timezone="Europe/Paris"),
                args=[exchange], id=f"scan_{exchange.lower()}_{hour}h",
            )

    # --- US: pre-scan at 15:15, deliver at 15:30 ---
    scheduler.add_job(
        _prescan_exchanges, CronTrigger(day_of_week="mon-fri", hour=15, minute=15, timezone="Europe/Paris"),
        args=[US_EXCHANGES, "15h30"], id="prescan_us_open",
    )
    scheduler.add_job(
        _deliver_results, CronTrigger(day_of_week="mon-fri", hour=15, minute=30, timezone="Europe/Paris"),
        args=[US_EXCHANGES, "15h30"], id="deliver_us_open",
    )

    # --- US rescans at 18:00 and 20:30 (scan + send immediately) ---
    for hour, minute in [(18, 0), (20, 30)]:
        for exchange in US_EXCHANGES:
            scheduler.add_job(
                _scan_and_send, CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute, timezone="Europe/Paris"),
                args=[exchange], id=f"scan_{exchange.lower()}_{hour}h{minute:02d}",
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
    """Scan all exchanges."""
    from scoring_engine.config import EXCHANGE_GROUPS
    from scoring_engine.pipeline import scan_exchange
    results = {}
    for exchange in EXCHANGE_GROUPS:
        results[exchange] = await scan_exchange(exchange)
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


@app.post("/api/backtest/v3")
async def api_v3_backtest():
    """Test 20 pro strategies (Connors RSI, IBS, streak, etc.) on 10yr data."""
    from scoring_engine.backtest.strategies_v3 import run_v3_backtest
    from scoring_engine.config import WATCHLIST
    return await run_v3_backtest(list(WATCHLIST.keys()))


@app.get("/api/backtest/calibration")
async def api_get_calibration():
    """Get current calibration table (win rates per score level)."""
    from scoring_engine.backtest.calibration import load_calibration
    return load_calibration()


@app.post("/api/backtest/multi-factor")
async def api_multi_factor_backtest():
    """Test 15+ strategies on 10 years of data. Find what actually works."""
    from scoring_engine.backtest.multi_factor import run_multi_factor_backtest
    from scoring_engine.config import WATCHLIST
    params = {t: {"t5d_threshold": w["t5d_threshold"], "rsi_threshold": w["rsi_threshold"],
                   "require_sma200": w["require_sma200"]}
              for t, w in WATCHLIST.items()}
    return await run_multi_factor_backtest(params)
