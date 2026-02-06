#!/bin/bash
# Load Test Script for IB_MCP Services
# Teste les endpoints /health et les APIs (sauf Claude)

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
CONCURRENCY=${1:-10}      # Concurrent requests
REQUESTS=${2:-100}        # Total requests
BASE_URL=${3:-"http://localhost"}

# Ports
MCP_SERVER_PORT=5002
MCP_MARKET_DATA_PORT=5003
MCP_SENTIMENT_PORT=5004
MCP_NEWS_PORT=5005

echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}   IB_MCP Load Test - ${CONCURRENCY} concurrent / ${REQUESTS} requests${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo ""

# Function to run ab test
run_test() {
    local name=$1
    local url=$2
    local method=${3:-GET}

    echo -e "${YELLOW}▶ Testing: ${name}${NC}"
    echo -e "  URL: ${url}"

    if [ "$method" == "GET" ]; then
        result=$(ab -n $REQUESTS -c $CONCURRENCY -q "$url" 2>&1)
    else
        result=$(ab -n $REQUESTS -c $CONCURRENCY -q -p /dev/null -T "application/json" "$url" 2>&1)
    fi

    # Extract key metrics
    rps=$(echo "$result" | grep "Requests per second" | awk '{print $4}')
    mean=$(echo "$result" | grep "Time per request" | head -1 | awk '{print $4}')
    failed=$(echo "$result" | grep "Failed requests" | awk '{print $3}')

    if [ "$failed" == "0" ]; then
        echo -e "  ${GREEN}✓ RPS: ${rps} | Mean: ${mean}ms | Failed: ${failed}${NC}"
    else
        echo -e "  ${RED}✗ RPS: ${rps} | Mean: ${mean}ms | Failed: ${failed}${NC}"
    fi
    echo ""
}

# Check services are up
echo -e "${BLUE}Checking services...${NC}"
for port in $MCP_SERVER_PORT $MCP_MARKET_DATA_PORT $MCP_SENTIMENT_PORT $MCP_NEWS_PORT; do
    if curl -sf "${BASE_URL}:${port}/health" > /dev/null 2>&1; then
        echo -e "  ${GREEN}✓ Port ${port} is up${NC}"
    else
        echo -e "  ${RED}✗ Port ${port} is down${NC}"
    fi
done
echo ""

echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}   Phase 1: Health Checks (baseline)${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo ""

run_test "mcp_server /health" "${BASE_URL}:${MCP_SERVER_PORT}/health"
run_test "mcp_market_data /health" "${BASE_URL}:${MCP_MARKET_DATA_PORT}/health"
run_test "mcp_sentiment /health" "${BASE_URL}:${MCP_SENTIMENT_PORT}/health"
run_test "mcp_news /health" "${BASE_URL}:${MCP_NEWS_PORT}/health"

echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}   Phase 2: API Endpoints (reduced load - external APIs)${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo ""

# Reduced load for external API calls to avoid rate limiting
API_REQUESTS=20
API_CONCURRENCY=2

echo -e "${YELLOW}⚠ Reduced load for external APIs: ${API_CONCURRENCY}c / ${API_REQUESTS}n${NC}"
echo ""

# Market Data - yfinance (local cache helps)
echo -e "${YELLOW}▶ Testing: mcp_market_data /stock/quote (yfinance)${NC}"
ab -n $API_REQUESTS -c $API_CONCURRENCY -q "${BASE_URL}:${MCP_MARKET_DATA_PORT}/stock/quote?symbols=AAPL" 2>&1 | grep -E "(Requests per second|Time per request|Failed)"
echo ""

# Market overview
echo -e "${YELLOW}▶ Testing: mcp_market_data /market/overview${NC}"
ab -n $API_REQUESTS -c $API_CONCURRENCY -q "${BASE_URL}:${MCP_MARKET_DATA_PORT}/market/overview" 2>&1 | grep -E "(Requests per second|Time per request|Failed)"
echo ""

echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}   Phase 3: Stress Test (health endpoints only)${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo ""

STRESS_CONCURRENCY=50
STRESS_REQUESTS=500

echo -e "${YELLOW}⚠ Stress test: ${STRESS_CONCURRENCY} concurrent / ${STRESS_REQUESTS} requests${NC}"
echo ""

run_test "STRESS mcp_market_data /health" "${BASE_URL}:${MCP_MARKET_DATA_PORT}/health"

echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}   Summary${NC}"
echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}"
echo ""

# Show docker stats
echo -e "${YELLOW}Docker Resource Usage:${NC}"
docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}" 2>/dev/null || echo "Docker stats not available"

echo ""
echo -e "${GREEN}Load test complete!${NC}"
