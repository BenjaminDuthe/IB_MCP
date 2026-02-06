"""
IB_MCP Load Testing with Locust
Professional load testing for market data, sentiment, and news services.
"""

from locust import HttpUser, task, between, events, tag
from locust.runners import MasterRunner, WorkerRunner
import time
import logging
from typing import Dict, Any

# Service configuration
SERVICES = {
    "market_data": {"host": "http://localhost:5003", "name": "mcp_market_data"},
    "sentiment": {"host": "http://localhost:5004", "name": "mcp_sentiment"},
    "news": {"host": "http://localhost:5005", "name": "mcp_news"},
}

# Metrics storage for custom reporting
metrics: Dict[str, Any] = {
    "start_time": None,
    "errors": [],
    "slow_requests": [],
}


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Initialize test metrics."""
    metrics["start_time"] = time.time()
    metrics["errors"] = []
    metrics["slow_requests"] = []
    logging.info("=" * 60)
    logging.info("IB_MCP Load Test Started")
    logging.info("=" * 60)


@events.request.add_listener
def on_request(request_type, name, response_time, response_length, response, context, exception, **kwargs):
    """Track slow requests and errors."""
    if exception:
        metrics["errors"].append({
            "name": name,
            "exception": str(exception),
            "time": time.time(),
        })
    elif response_time > 2000:  # > 2 seconds
        metrics["slow_requests"].append({
            "name": name,
            "response_time": response_time,
            "time": time.time(),
        })


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Generate summary report."""
    duration = time.time() - metrics["start_time"] if metrics["start_time"] else 0
    logging.info("=" * 60)
    logging.info("IB_MCP Load Test Completed")
    logging.info(f"Duration: {duration:.1f}s")
    logging.info(f"Total Errors: {len(metrics['errors'])}")
    logging.info(f"Slow Requests (>2s): {len(metrics['slow_requests'])}")
    logging.info("=" * 60)


# =============================================================================
# Health Check Users - Lightweight baseline tests
# =============================================================================

class HealthCheckUser(HttpUser):
    """Fast health check testing for baseline performance."""

    host = "http://localhost:5003"  # Default host (required by Locust)
    wait_time = between(0.1, 0.5)
    weight = 1  # Lower weight, fewer users

    @tag("health", "market_data")
    @task(1)
    def health_market_data(self):
        with self.client.get(
            f"{SERVICES['market_data']['host']}/health",
            name="/health [market_data]",
            catch_response=True
        ) as response:
            if response.status_code != 200:
                response.failure(f"Health check failed: {response.status_code}")

    @tag("health", "sentiment")
    @task(1)
    def health_sentiment(self):
        with self.client.get(
            f"{SERVICES['sentiment']['host']}/health",
            name="/health [sentiment]",
            catch_response=True
        ) as response:
            if response.status_code != 200:
                response.failure(f"Health check failed: {response.status_code}")

    @tag("health", "news")
    @task(1)
    def health_news(self):
        with self.client.get(
            f"{SERVICES['news']['host']}/health",
            name="/health [news]",
            catch_response=True
        ) as response:
            if response.status_code != 200:
                response.failure(f"Health check failed: {response.status_code}")


# =============================================================================
# Market Data API User
# =============================================================================

class MarketDataUser(HttpUser):
    """Test market data service endpoints (yfinance-based)."""

    wait_time = between(1, 3)
    weight = 3
    host = SERVICES["market_data"]["host"]

    # Stock symbols to test with
    symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]

    def get_random_symbol(self):
        import random
        return random.choice(self.symbols)

    @tag("api", "market_data", "price")
    @task(5)
    def stock_price(self):
        """Get stock price - most common operation."""
        symbol = self.get_random_symbol()
        with self.client.get(
            f"/stock/price/{symbol}",
            name="/stock/price/[symbol]",
            catch_response=True,
            timeout=30
        ) as response:
            if response.status_code == 200:
                try:
                    data = response.json()
                    if "error" in data:
                        response.failure(f"API error: {data['error']}")
                except Exception as e:
                    response.failure(f"JSON parse error: {e}")
            elif response.status_code == 429:
                response.failure("Rate limited")
            else:
                response.failure(f"Status {response.status_code}")

    @tag("api", "market_data", "fundamentals")
    @task(2)
    def stock_fundamentals(self):
        """Get fundamentals - heavier operation."""
        symbol = self.get_random_symbol()
        with self.client.get(
            f"/stock/fundamentals/{symbol}",
            name="/stock/fundamentals/[symbol]",
            catch_response=True,
            timeout=30
        ) as response:
            if response.status_code == 200:
                try:
                    response.json()
                except Exception as e:
                    response.failure(f"JSON parse error: {e}")
            else:
                response.failure(f"Status {response.status_code}")

    @tag("api", "market_data", "overview")
    @task(1)
    def market_overview(self):
        """Market overview - slowest endpoint (~8s expected)."""
        with self.client.get(
            "/market/overview",
            name="/market/overview",
            catch_response=True,
            timeout=60  # Extended timeout for slow endpoint
        ) as response:
            if response.status_code == 200:
                try:
                    response.json()
                except Exception as e:
                    response.failure(f"JSON parse error: {e}")
            else:
                response.failure(f"Status {response.status_code}")


# =============================================================================
# Sentiment API User
# =============================================================================

class SentimentUser(HttpUser):
    """Test sentiment analysis service endpoints."""

    wait_time = between(2, 5)
    weight = 2
    host = SERVICES["sentiment"]["host"]

    symbols = ["AAPL", "TSLA", "GME", "AMC", "NVDA"]

    def get_random_symbol(self):
        import random
        return random.choice(self.symbols)

    @tag("api", "sentiment", "stocktwits")
    @task(3)
    def sentiment_stocktwits(self):
        """StockTwits sentiment - external API dependency."""
        symbol = self.get_random_symbol()
        with self.client.get(
            f"/sentiment/stocktwits/{symbol}",
            name="/sentiment/stocktwits/[symbol]",
            catch_response=True,
            timeout=30
        ) as response:
            if response.status_code == 200:
                try:
                    response.json()
                except Exception as e:
                    response.failure(f"JSON parse error: {e}")
            elif response.status_code == 429:
                response.failure("StockTwits rate limit")
            else:
                response.failure(f"Status {response.status_code}")

    @tag("api", "sentiment", "reddit")
    @task(2)
    def sentiment_reddit(self):
        """Reddit sentiment - requires PRAW config."""
        symbol = self.get_random_symbol()
        with self.client.get(
            f"/sentiment/reddit/{symbol}",
            name="/sentiment/reddit/[symbol]",
            catch_response=True,
            timeout=30
        ) as response:
            # May fail if Reddit API not configured
            if response.status_code in [200, 500]:
                pass  # Accept 500 as "not configured"
            elif response.status_code == 429:
                response.failure("Reddit rate limit")


# =============================================================================
# News API User
# =============================================================================

class NewsUser(HttpUser):
    """Test news service endpoints (Finnhub-based)."""

    wait_time = between(2, 5)
    weight = 2
    host = SERVICES["news"]["host"]

    symbols = ["AAPL", "MSFT", "GOOGL", "META", "NVDA"]

    def get_random_symbol(self):
        import random
        return random.choice(self.symbols)

    @tag("api", "news", "stock")
    @task(3)
    def news_stock(self):
        """Stock news from Finnhub."""
        symbol = self.get_random_symbol()
        with self.client.get(
            f"/news/stock/{symbol}",
            name="/news/stock/[symbol]",
            catch_response=True,
            timeout=30
        ) as response:
            if response.status_code == 200:
                try:
                    response.json()
                except Exception as e:
                    response.failure(f"JSON parse error: {e}")
            elif response.status_code == 429:
                response.failure("Finnhub rate limit")
            else:
                response.failure(f"Status {response.status_code}")

    @tag("api", "news", "earnings")
    @task(2)
    def earnings_calendar(self):
        """Earnings calendar."""
        with self.client.get(
            "/news/earnings",
            name="/earnings",
            catch_response=True,
            timeout=30
        ) as response:
            if response.status_code == 200:
                try:
                    response.json()
                except Exception as e:
                    response.failure(f"JSON parse error: {e}")
            else:
                response.failure(f"Status {response.status_code}")

    @tag("api", "news", "market")
    @task(1)
    def news_market(self):
        """General market news."""
        with self.client.get(
            "/news/market",
            name="/news/market",
            catch_response=True,
            timeout=30
        ) as response:
            if response.status_code == 200:
                try:
                    response.json()
                except Exception as e:
                    response.failure(f"JSON parse error: {e}")
            else:
                response.failure(f"Status {response.status_code}")


# =============================================================================
# Combined Realistic User (simulates real usage pattern)
# =============================================================================

class RealisticTraderUser(HttpUser):
    """
    Simulates a realistic trader workflow:
    1. Check market overview
    2. Get stock prices
    3. Check sentiment
    4. Read news
    """

    host = "http://localhost:5003"  # Default host (required by Locust)
    wait_time = between(3, 8)
    weight = 5  # Most common user type

    symbols = ["AAPL", "MSFT", "GOOGL", "NVDA", "TSLA"]

    def get_random_symbol(self):
        import random
        return random.choice(self.symbols)

    @tag("workflow", "price")
    @task(10)
    def check_price(self):
        """Quick price check - most frequent action."""
        symbol = self.get_random_symbol()
        self.client.get(
            f"{SERVICES['market_data']['host']}/stock/price/{symbol}",
            name="[trader] price check",
            timeout=15
        )

    @tag("workflow", "sentiment")
    @task(5)
    def check_sentiment(self):
        """Check sentiment before trading."""
        symbol = self.get_random_symbol()
        self.client.get(
            f"{SERVICES['sentiment']['host']}/sentiment/stocktwits/{symbol}",
            name="[trader] sentiment",
            timeout=15
        )

    @tag("workflow", "news")
    @task(3)
    def check_news(self):
        """Read latest news."""
        symbol = self.get_random_symbol()
        self.client.get(
            f"{SERVICES['news']['host']}/news/stock/{symbol}",
            name="[trader] news",
            timeout=15
        )

    @tag("workflow", "fundamentals")
    @task(1)
    def deep_analysis(self):
        """Occasional deep dive into fundamentals."""
        symbol = self.get_random_symbol()
        self.client.get(
            f"{SERVICES['market_data']['host']}/stock/fundamentals/{symbol}",
            name="[trader] fundamentals",
            timeout=30
        )
