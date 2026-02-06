#!/bin/bash
#
# IB_MCP Load Test Runner
# Usage: ./scripts/run_load_test.sh [profile] [options]
#
# Profiles:
#   quick     - 5 users, 30s (smoke test)
#   baseline  - 10 users, 1m (baseline)
#   normal    - 25 users, 3m (normal load)
#   stress    - 50 users, 5m (stress test)
#   spike     - 100 users, 2m (spike test)
#   endurance - 20 users, 30m (long-running)
#
# Options:
#   --web      Start web UI instead of headless mode
#   --docker   Monitor Docker stats during test
#   --tags     Comma-separated list of tags to include
#

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOCUSTFILE="$PROJECT_DIR/tests/locustfile.py"
REPORTS_DIR="$PROJECT_DIR/reports"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default profile
PROFILE="${1:-baseline}"
shift 2>/dev/null || true

# Parse options
WEB_MODE=false
DOCKER_STATS=false
TAGS=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --web)
            WEB_MODE=true
            shift
            ;;
        --docker)
            DOCKER_STATS=true
            shift
            ;;
        --tags)
            TAGS="$2"
            shift 2
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            exit 1
            ;;
    esac
done

# Profile configurations
case $PROFILE in
    quick)
        USERS=5
        SPAWN_RATE=1
        DURATION="30s"
        TAGS="${TAGS:-health}"
        ;;
    baseline)
        USERS=10
        SPAWN_RATE=2
        DURATION="1m"
        ;;
    normal)
        USERS=25
        SPAWN_RATE=5
        DURATION="3m"
        ;;
    stress)
        USERS=50
        SPAWN_RATE=10
        DURATION="5m"
        ;;
    spike)
        USERS=100
        SPAWN_RATE=50
        DURATION="2m"
        ;;
    endurance)
        USERS=20
        SPAWN_RATE=2
        DURATION="30m"
        ;;
    *)
        echo -e "${RED}Unknown profile: $PROFILE${NC}"
        echo "Available profiles: quick, baseline, normal, stress, spike, endurance"
        exit 1
        ;;
esac

# Create reports directory
mkdir -p "$REPORTS_DIR"

# Report file names
HTML_REPORT="$REPORTS_DIR/load_test_${PROFILE}_${TIMESTAMP}.html"
CSV_PREFIX="$REPORTS_DIR/load_test_${PROFILE}_${TIMESTAMP}"

# Header
echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
PROFILE_UPPER=$(echo "$PROFILE" | tr '[:lower:]' '[:upper:]')
echo -e "${BLUE}   IB_MCP Load Test - ${PROFILE_UPPER} Profile${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${GREEN}Configuration:${NC}"
echo "  Users:      $USERS"
echo "  Spawn Rate: $SPAWN_RATE/s"
echo "  Duration:   $DURATION"
echo "  Tags:       ${TAGS:-all}"
echo "  Report:     $HTML_REPORT"
echo ""

# Check if services are running
echo -e "${YELLOW}Checking services...${NC}"

check_service() {
    local name=$1
    local port=$2
    if curl -s --connect-timeout 2 "http://localhost:$port/health" > /dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} $name (port $port)"
        return 0
    else
        echo -e "  ${RED}✗${NC} $name (port $port) - NOT RUNNING"
        return 1
    fi
}

SERVICES_OK=true
check_service "mcp_market_data" 5003 || SERVICES_OK=false
check_service "mcp_sentiment" 5004 || SERVICES_OK=false
check_service "mcp_news" 5005 || SERVICES_OK=false

echo ""

if [ "$SERVICES_OK" = false ]; then
    echo -e "${RED}Some services are not running!${NC}"
    echo "Start services with: docker compose up -d"
    exit 1
fi

# Start Docker stats monitoring if requested
DOCKER_STATS_PID=""
if [ "$DOCKER_STATS" = true ]; then
    echo -e "${YELLOW}Starting Docker stats monitoring...${NC}"
    DOCKER_STATS_FILE="$REPORTS_DIR/docker_stats_${TIMESTAMP}.log"
    docker stats --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}" \
        mcp_market_data mcp_sentiment mcp_news 2>/dev/null > "$DOCKER_STATS_FILE" &
    DOCKER_STATS_PID=$!
    echo "  Docker stats → $DOCKER_STATS_FILE"
    echo ""
fi

# Build locust command
LOCUST_CMD="locust -f $LOCUSTFILE"

if [ "$WEB_MODE" = true ]; then
    echo -e "${GREEN}Starting Locust Web UI on http://localhost:8089${NC}"
    echo "Press Ctrl+C to stop"
    echo ""
    $LOCUST_CMD
else
    # Build headless command
    LOCUST_CMD="$LOCUST_CMD --headless"
    LOCUST_CMD="$LOCUST_CMD -u $USERS"
    LOCUST_CMD="$LOCUST_CMD -r $SPAWN_RATE"
    LOCUST_CMD="$LOCUST_CMD -t $DURATION"
    LOCUST_CMD="$LOCUST_CMD --html $HTML_REPORT"
    LOCUST_CMD="$LOCUST_CMD --csv $CSV_PREFIX"

    # Add tags filter if specified
    if [ -n "$TAGS" ]; then
        LOCUST_CMD="$LOCUST_CMD --tags $TAGS"
    fi

    echo -e "${GREEN}Running load test...${NC}"
    echo ""

    # Run locust
    $LOCUST_CMD

    echo ""
    echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}   Load Test Complete${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
    echo ""
    echo -e "${BLUE}Reports generated:${NC}"
    echo "  HTML Report: $HTML_REPORT"
    echo "  CSV Stats:   ${CSV_PREFIX}_stats.csv"
    echo "  CSV History: ${CSV_PREFIX}_stats_history.csv"
    echo "  CSV Failures: ${CSV_PREFIX}_failures.csv"
fi

# Stop Docker stats monitoring
if [ -n "$DOCKER_STATS_PID" ]; then
    kill $DOCKER_STATS_PID 2>/dev/null || true
    echo ""
    echo -e "${BLUE}Docker stats saved to:${NC}"
    echo "  $DOCKER_STATS_FILE"
fi

# Generate summary from CSV
if [ -f "${CSV_PREFIX}_stats.csv" ]; then
    echo ""
    echo -e "${YELLOW}Quick Summary:${NC}"
    echo ""

    # Parse CSV and display summary
    python3 - <<EOF
import csv
import sys

try:
    with open("${CSV_PREFIX}_stats.csv", 'r') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Find aggregated row
    for row in rows:
        if row.get('Name', '') == 'Aggregated':
            print(f"  Total Requests:    {row.get('Request Count', 'N/A')}")
            print(f"  Total Failures:    {row.get('Failure Count', 'N/A')}")
            print(f"  Avg Response Time: {float(row.get('Average Response Time', 0)):.0f}ms")
            print(f"  p50:               {float(row.get('50%', 0)):.0f}ms")
            print(f"  p95:               {float(row.get('95%', 0)):.0f}ms")
            print(f"  p99:               {float(row.get('99%', 0)):.0f}ms")
            print(f"  RPS:               {float(row.get('Requests/s', 0)):.2f}")
            break
except Exception as e:
    print(f"  Could not parse CSV: {e}")
EOF
fi

echo ""
echo -e "${GREEN}Open the HTML report for detailed analysis:${NC}"
echo "  open $HTML_REPORT"
echo ""
