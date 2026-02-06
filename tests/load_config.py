"""
IB_MCP Load Test Configuration
Defines thresholds, alerts, and anomaly detection rules.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum


class Severity(Enum):
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Threshold:
    """Threshold configuration for a metric."""
    ok_max: float
    warning_max: float
    unit: str = "ms"

    def evaluate(self, value: float) -> Severity:
        if value <= self.ok_max:
            return Severity.OK
        elif value <= self.warning_max:
            return Severity.WARNING
        else:
            return Severity.CRITICAL


@dataclass
class EndpointConfig:
    """Configuration for a specific endpoint."""
    path: str
    expected_p50_ms: float
    expected_p95_ms: float
    expected_p99_ms: float
    timeout_ms: float = 30000
    expected_error_rate: float = 0.0
    notes: str = ""


@dataclass
class ServiceConfig:
    """Configuration for a service."""
    name: str
    port: int
    host: str = "localhost"
    endpoints: Dict[str, EndpointConfig] = field(default_factory=dict)
    expected_rps: float = 10.0


# =============================================================================
# Threshold Definitions
# =============================================================================

THRESHOLDS = {
    # Response time thresholds
    "response_time_p50": Threshold(ok_max=100, warning_max=500, unit="ms"),
    "response_time_p95": Threshold(ok_max=500, warning_max=2000, unit="ms"),
    "response_time_p99": Threshold(ok_max=2000, warning_max=5000, unit="ms"),

    # Error rate thresholds
    "error_rate": Threshold(ok_max=0.0, warning_max=1.0, unit="%"),

    # RPS thresholds (inverted - lower is worse)
    "rps_health": Threshold(ok_max=500, warning_max=1000, unit="req/s"),
    "rps_api": Threshold(ok_max=5, warning_max=10, unit="req/s"),

    # Resource usage
    "cpu_usage": Threshold(ok_max=50, warning_max=80, unit="%"),
    "memory_usage": Threshold(ok_max=70, warning_max=90, unit="%"),
}


# =============================================================================
# Service Configurations
# =============================================================================

SERVICES = {
    "mcp_market_data": ServiceConfig(
        name="mcp_market_data",
        port=5003,
        expected_rps=20.0,
        endpoints={
            "/health": EndpointConfig(
                path="/health",
                expected_p50_ms=10,
                expected_p95_ms=50,
                expected_p99_ms=100,
                notes="Health check - should be instant"
            ),
            "/stock/price": EndpointConfig(
                path="/stock/price/{symbol}",
                expected_p50_ms=200,
                expected_p95_ms=500,
                expected_p99_ms=1000,
                notes="yfinance price fetch"
            ),
            "/stock/fundamentals": EndpointConfig(
                path="/stock/fundamentals/{symbol}",
                expected_p50_ms=500,
                expected_p95_ms=1500,
                expected_p99_ms=3000,
                notes="Heavy yfinance query"
            ),
            "/market/overview": EndpointConfig(
                path="/market/overview",
                expected_p50_ms=5000,
                expected_p95_ms=8000,
                expected_p99_ms=15000,
                timeout_ms=60000,
                notes="Known slow endpoint - fetches multiple indices"
            ),
        }
    ),
    "mcp_sentiment": ServiceConfig(
        name="mcp_sentiment",
        port=5004,
        expected_rps=10.0,
        endpoints={
            "/health": EndpointConfig(
                path="/health",
                expected_p50_ms=10,
                expected_p95_ms=50,
                expected_p99_ms=100,
                notes="Health check"
            ),
            "/sentiment/stocktwits": EndpointConfig(
                path="/sentiment/stocktwits/{symbol}",
                expected_p50_ms=300,
                expected_p95_ms=800,
                expected_p99_ms=2000,
                notes="StockTwits API - may be rate limited"
            ),
            "/sentiment/reddit": EndpointConfig(
                path="/sentiment/reddit/{symbol}",
                expected_p50_ms=500,
                expected_p95_ms=1500,
                expected_p99_ms=3000,
                expected_error_rate=10.0,  # May fail if not configured
                notes="Reddit API via PRAW - requires credentials"
            ),
        }
    ),
    "mcp_news": ServiceConfig(
        name="mcp_news",
        port=5005,
        expected_rps=10.0,
        endpoints={
            "/health": EndpointConfig(
                path="/health",
                expected_p50_ms=10,
                expected_p95_ms=50,
                expected_p99_ms=100,
                notes="Health check"
            ),
            "/news/stock": EndpointConfig(
                path="/news/stock/{symbol}",
                expected_p50_ms=300,
                expected_p95_ms=800,
                expected_p99_ms=2000,
                notes="Finnhub news API"
            ),
            "/earnings": EndpointConfig(
                path="/earnings",
                expected_p50_ms=200,
                expected_p95_ms=600,
                expected_p99_ms=1500,
                notes="Earnings calendar"
            ),
            "/news/market": EndpointConfig(
                path="/news/market",
                expected_p50_ms=300,
                expected_p95_ms=800,
                expected_p99_ms=2000,
                notes="General market news"
            ),
        }
    ),
}


# =============================================================================
# Anomaly Detection Rules
# =============================================================================

@dataclass
class AnomalyRule:
    """Rule for detecting anomalies."""
    name: str
    description: str
    check: str  # Python expression to evaluate
    severity: Severity
    action: str


ANOMALY_RULES: List[AnomalyRule] = [
    AnomalyRule(
        name="timeout",
        description="Response time exceeds 30 seconds",
        check="response_time > 30000",
        severity=Severity.CRITICAL,
        action="Check external API connectivity (yfinance, Finnhub, StockTwits)"
    ),
    AnomalyRule(
        name="rate_limiting",
        description="HTTP 429 errors detected",
        check="status_code == 429",
        severity=Severity.WARNING,
        action="Reduce concurrent users or add request throttling"
    ),
    AnomalyRule(
        name="connection_refused",
        description="Connection refused errors",
        check="'Connection refused' in error_message",
        severity=Severity.CRITICAL,
        action="Verify service is running and port is correct"
    ),
    AnomalyRule(
        name="high_error_rate",
        description="Error rate exceeds 5%",
        check="error_rate > 5",
        severity=Severity.CRITICAL,
        action="Check service logs for exceptions"
    ),
    AnomalyRule(
        name="slow_endpoint",
        description="p95 latency exceeds 5 seconds",
        check="p95 > 5000",
        severity=Severity.WARNING,
        action="Consider caching or optimizing the endpoint"
    ),
    AnomalyRule(
        name="memory_growth",
        description="Memory usage increasing over time",
        check="memory_delta > 100",
        severity=Severity.WARNING,
        action="Potential memory leak - profile the service"
    ),
    AnomalyRule(
        name="cpu_saturation",
        description="CPU usage exceeds 90%",
        check="cpu_usage > 90",
        severity=Severity.CRITICAL,
        action="Increase CPU limits or optimize code"
    ),
]


# =============================================================================
# Test Profiles
# =============================================================================

@dataclass
class TestProfile:
    """Predefined test profile."""
    name: str
    description: str
    users: int
    spawn_rate: float
    duration: str
    tags: Optional[List[str]] = None


TEST_PROFILES = {
    "quick": TestProfile(
        name="quick",
        description="Quick smoke test",
        users=5,
        spawn_rate=1,
        duration="30s",
        tags=["health"]
    ),
    "baseline": TestProfile(
        name="baseline",
        description="Baseline performance test",
        users=10,
        spawn_rate=2,
        duration="1m"
    ),
    "normal": TestProfile(
        name="normal",
        description="Normal load test",
        users=25,
        spawn_rate=5,
        duration="3m"
    ),
    "stress": TestProfile(
        name="stress",
        description="Stress test with high load",
        users=50,
        spawn_rate=10,
        duration="5m"
    ),
    "spike": TestProfile(
        name="spike",
        description="Spike test - sudden traffic burst",
        users=100,
        spawn_rate=50,
        duration="2m"
    ),
    "endurance": TestProfile(
        name="endurance",
        description="Long-running endurance test",
        users=20,
        spawn_rate=2,
        duration="30m"
    ),
}


def get_service_url(service_name: str) -> str:
    """Get the base URL for a service."""
    config = SERVICES.get(service_name)
    if config:
        return f"http://{config.host}:{config.port}"
    raise ValueError(f"Unknown service: {service_name}")


def evaluate_metrics(metrics: Dict) -> List[Dict]:
    """
    Evaluate metrics against thresholds and return anomalies.

    Args:
        metrics: Dictionary with keys like 'p50', 'p95', 'p99', 'error_rate', etc.

    Returns:
        List of detected anomalies with severity and recommendations.
    """
    anomalies = []

    # Check response times
    if "p50" in metrics:
        result = THRESHOLDS["response_time_p50"].evaluate(metrics["p50"])
        if result != Severity.OK:
            anomalies.append({
                "metric": "p50",
                "value": metrics["p50"],
                "severity": result,
                "message": f"p50 latency is {metrics['p50']:.0f}ms"
            })

    if "p95" in metrics:
        result = THRESHOLDS["response_time_p95"].evaluate(metrics["p95"])
        if result != Severity.OK:
            anomalies.append({
                "metric": "p95",
                "value": metrics["p95"],
                "severity": result,
                "message": f"p95 latency is {metrics['p95']:.0f}ms"
            })

    if "p99" in metrics:
        result = THRESHOLDS["response_time_p99"].evaluate(metrics["p99"])
        if result != Severity.OK:
            anomalies.append({
                "metric": "p99",
                "value": metrics["p99"],
                "severity": result,
                "message": f"p99 latency is {metrics['p99']:.0f}ms"
            })

    # Check error rate
    if "error_rate" in metrics:
        result = THRESHOLDS["error_rate"].evaluate(metrics["error_rate"])
        if result != Severity.OK:
            anomalies.append({
                "metric": "error_rate",
                "value": metrics["error_rate"],
                "severity": result,
                "message": f"Error rate is {metrics['error_rate']:.2f}%"
            })

    return anomalies
