import os
import json
import logging
import aiosqlite
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "/data/trading.db")
SCHEMA_PATH = os.environ.get("SCHEMA_PATH", "/app/shared/db_schema.sql")


async def init_db():
    """Initialize the database with schema if tables don't exist, then run migrations."""
    async with aiosqlite.connect(DB_PATH) as db:
        if os.path.exists(SCHEMA_PATH):
            with open(SCHEMA_PATH, "r") as f:
                schema = f.read()
            await db.executescript(schema)
        else:
            logger.warning(f"Schema file not found at {SCHEMA_PATH}")

        # Migrations: add columns if they don't exist (idempotent)
        cursor = await db.execute("PRAGMA table_info(trade_signals)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "stop_loss" not in columns:
            await db.execute("ALTER TABLE trade_signals ADD COLUMN stop_loss REAL")
        if "take_profit" not in columns:
            await db.execute("ALTER TABLE trade_signals ADD COLUMN take_profit REAL")

        await db.commit()


async def insert_trade_signal(
    ticker: str,
    action: str,
    quantity: Optional[float],
    order_type: Optional[str],
    price: Optional[float],
    confidence: Optional[float],
    reason: Optional[str],
    status: str = "pending",
    safety_check_result: Optional[str] = None,
    telegram_message_id: Optional[int] = None,
    stop_loss: Optional[float] = None,
    take_profit: Optional[float] = None,
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO trade_signals
               (ticker, action, quantity, order_type, price, confidence, reason, status, safety_check_result, telegram_message_id, stop_loss, take_profit)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ticker, action, quantity, order_type, price, confidence, reason, status, safety_check_result, telegram_message_id, stop_loss, take_profit),
        )
        await db.commit()
        return cursor.lastrowid


async def update_signal_status(
    signal_id: int,
    status: str,
    user_decision: Optional[str] = None,
):
    async with aiosqlite.connect(DB_PATH) as db:
        if user_decision:
            await db.execute(
                "UPDATE trade_signals SET status=?, user_decision=?, user_decision_at=? WHERE id=?",
                (status, user_decision, datetime.now().isoformat(), signal_id),
            )
        else:
            await db.execute(
                "UPDATE trade_signals SET status=? WHERE id=?",
                (status, signal_id),
            )
        await db.commit()


async def get_pending_signals() -> list[dict]:
    """Get all pending trade signals (for reload after restart)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM trade_signals WHERE status='pending' ORDER BY created_at ASC"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def insert_trade_history(
    signal_id: int,
    ticker: str,
    action: str,
    quantity: float,
    order_type: str,
    price: Optional[float],
    ib_order_id: Optional[str] = None,
    status: str = "submitted",
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """INSERT INTO trade_history
               (signal_id, ticker, action, quantity, order_type, price, ib_order_id, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (signal_id, ticker, action, quantity, order_type, price, ib_order_id, status),
        )
        await db.commit()
        return cursor.lastrowid


async def get_trade_history(limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM trade_history ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def insert_portfolio_snapshot(
    account_id: str,
    total_value: Optional[float],
    cash_balance: Optional[float],
    unrealized_pnl: Optional[float],
    positions_json: Optional[str],
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO portfolio_snapshots
               (account_id, total_value, cash_balance, unrealized_pnl, positions_json)
               VALUES (?, ?, ?, ?, ?)""",
            (account_id, total_value, cash_balance, unrealized_pnl, positions_json),
        )
        await db.commit()


async def get_system_state(key: str) -> Optional[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT value FROM system_state WHERE key=?", (key,)
        )
        row = await cursor.fetchone()
        return row[0] if row else None


async def set_system_state(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO system_state (key, value, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
            (key, value, datetime.now().isoformat()),
        )
        await db.commit()


async def insert_analysis_log(
    trigger_type: str,
    ticker: Optional[str],
    prompt: Optional[str],
    response: Optional[str],
    tools_used: Optional[list],
    tokens_input: Optional[int],
    tokens_output: Optional[int],
    telegram_message_id: Optional[int] = None,
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO analysis_logs
               (trigger_type, ticker, prompt, response, tools_used, tokens_input, tokens_output, telegram_message_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (trigger_type, ticker, prompt, response, json.dumps(tools_used) if tools_used else None, tokens_input, tokens_output, telegram_message_id),
        )
        await db.commit()


async def get_daily_order_count() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM trade_history WHERE date(created_at)=date('now')"
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


async def get_daily_pnl() -> float:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT COALESCE(SUM(pnl), 0) FROM trade_history WHERE date(created_at)=date('now') AND pnl IS NOT NULL"
        )
        row = await cursor.fetchone()
        return float(row[0]) if row else 0.0


# ============================================
# B1: Performance stats
# ============================================

async def get_performance_stats() -> dict:
    """Get comprehensive trading performance statistics."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Signal stats by status
        cursor = await db.execute(
            "SELECT status, COUNT(*) FROM trade_signals GROUP BY status"
        )
        signal_stats = {row[0]: row[1] for row in await cursor.fetchall()}

        # Trade stats
        cursor = await db.execute(
            "SELECT COUNT(*), "
            "SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN pnl IS NOT NULL THEN pnl ELSE 0 END), "
            "MAX(pnl), MIN(pnl), AVG(pnl), "
            "SUM(CASE WHEN pnl IS NULL THEN 1 ELSE 0 END) "
            "FROM trade_history"
        )
        row = await cursor.fetchone()
        trade_stats = {
            "total": row[0] or 0,
            "winners": row[1] or 0,
            "losers": row[2] or 0,
            "cumulative_pnl": row[3] or 0.0,
            "best_pnl": row[4],
            "worst_pnl": row[5],
            "avg_pnl": row[6],
            "null_pnl_count": row[7] or 0,
        }

        # Best trade details
        cursor = await db.execute(
            "SELECT ticker, pnl FROM trade_history WHERE pnl IS NOT NULL ORDER BY pnl DESC LIMIT 1"
        )
        best = await cursor.fetchone()
        trade_stats["best_trade"] = {"ticker": best[0], "pnl": best[1]} if best else None

        # Worst trade details
        cursor = await db.execute(
            "SELECT ticker, pnl FROM trade_history WHERE pnl IS NOT NULL ORDER BY pnl ASC LIMIT 1"
        )
        worst = await cursor.fetchone()
        trade_stats["worst_trade"] = {"ticker": worst[0], "pnl": worst[1]} if worst else None

        # Token usage from analysis_logs
        cursor = await db.execute(
            "SELECT COUNT(*), COALESCE(SUM(tokens_input), 0), COALESCE(SUM(tokens_output), 0) FROM analysis_logs"
        )
        token_row = await cursor.fetchone()
        token_stats = {
            "analysis_count": token_row[0] or 0,
            "total_tokens_input": token_row[1] or 0,
            "total_tokens_output": token_row[2] or 0,
        }

        return {
            "signals": signal_stats,
            "trades": trade_stats,
            "tokens": token_stats,
        }


# ============================================
# B2: Order fill tracking
# ============================================

async def get_pending_orders() -> list[dict]:
    """Get orders that are submitted and awaiting fill."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM trade_history WHERE status='submitted' AND ib_order_id IS NOT NULL ORDER BY created_at ASC"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def update_trade_fill(
    trade_id: int,
    status: str,
    filled_price: Optional[float] = None,
    filled_at: Optional[str] = None,
    commission: Optional[float] = None,
    pnl: Optional[float] = None,
):
    """Update a trade with fill information."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE trade_history SET status=?, filled_price=?, filled_at=?, commission=?, pnl=? WHERE id=?",
            (status, filled_price, filled_at, commission, pnl, trade_id),
        )
        await db.commit()


# ============================================
# C1: Watchlist
# ============================================

async def add_watchlist_ticker(ticker: str) -> bool:
    """Add a ticker to watchlist. Returns True if added, False if already exists."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO watchlist (ticker) VALUES (?)", (ticker.upper(),)
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def remove_watchlist_ticker(ticker: str) -> bool:
    """Remove a ticker from watchlist. Returns True if removed."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM watchlist WHERE ticker=?", (ticker.upper(),)
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_watchlist() -> list[dict]:
    """Get all watchlist tickers."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM watchlist ORDER BY added_at ASC"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


async def update_watchlist_price(ticker: str, price: float):
    """Update last known price for a watchlist ticker."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE watchlist SET last_price=?, last_check_at=? WHERE ticker=?",
            (price, datetime.now().isoformat(), ticker.upper()),
        )
        await db.commit()


async def update_watchlist_alert(ticker: str):
    """Update last alert time for a watchlist ticker."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE watchlist SET last_alert_at=? WHERE ticker=?",
            (datetime.now().isoformat(), ticker.upper()),
        )
        await db.commit()
