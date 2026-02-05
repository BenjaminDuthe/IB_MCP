PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS trade_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL CHECK(action IN ('BUY','SELL','HOLD')),
    quantity REAL,
    order_type TEXT,
    price REAL,
    confidence REAL,
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending','approved','rejected','expired','executed','failed','safety_blocked')),
    safety_check_result TEXT,
    user_decision TEXT,
    user_decision_at TIMESTAMP,
    telegram_message_id INTEGER,
    stop_loss REAL,
    take_profit REAL
);

CREATE TABLE IF NOT EXISTS trade_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER REFERENCES trade_signals(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL,
    quantity REAL NOT NULL,
    order_type TEXT NOT NULL,
    price REAL,
    filled_price REAL,
    filled_at TIMESTAMP,
    ib_order_id TEXT,
    status TEXT NOT NULL DEFAULT 'submitted',
    commission REAL,
    pnl REAL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    account_id TEXT NOT NULL,
    total_value REAL,
    cash_balance REAL,
    unrealized_pnl REAL,
    positions_json TEXT
);

CREATE TABLE IF NOT EXISTS system_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analysis_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    trigger_type TEXT NOT NULL,
    ticker TEXT,
    prompt TEXT,
    response TEXT,
    tools_used TEXT,
    tokens_input INTEGER,
    tokens_output INTEGER,
    telegram_message_id INTEGER
);

CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL UNIQUE,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_alert_at TIMESTAMP,
    last_price REAL,
    last_check_at TIMESTAMP
);
