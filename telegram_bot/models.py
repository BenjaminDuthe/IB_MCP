from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class TradeAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class SignalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    EXECUTED = "executed"
    FAILED = "failed"
    SAFETY_BLOCKED = "safety_blocked"


class TradeSignal(BaseModel):
    ticker: str
    action: TradeAction
    quantity: Optional[float] = None
    order_type: Optional[str] = None
    price: Optional[float] = None
    confidence: Optional[float] = None
    reason: Optional[str] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


class SafetyCheckResult(BaseModel):
    passed: bool
    checks: dict = Field(default_factory=dict)
    blocked_reason: Optional[str] = None


class MCPServerConfig(BaseModel):
    name: str
    url: str
    prefix: str
