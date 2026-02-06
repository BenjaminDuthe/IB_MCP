#!/usr/bin/env python3
"""
IB_MCP Load Test Results Analyzer
Generates anomaly reports from Locust CSV output.
"""

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from load_config import (
    SERVICES,
    THRESHOLDS,
    ANOMALY_RULES,
    Severity,
    evaluate_metrics,
)


@dataclass
class EndpointResult:
    """Results for a single endpoint."""
    name: str
    request_count: int
    failure_count: int
    avg_response_time: float
    min_response_time: float
    max_response_time: float
    p50: float
    p95: float
    p99: float
    rps: float
    error_rate: float


@dataclass
class Anomaly:
    """Detected anomaly."""
    severity: Severity
    service: str
    endpoint: str
    description: str
    value: float
    threshold: float
    recommendation: str


def parse_stats_csv(filepath: str) -> List[EndpointResult]:
    """Parse Locust stats CSV file."""
    results = []

    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get('Name', '')
            if not name or name == 'Aggregated':
                continue

            request_count = int(row.get('Request Count', 0))
            failure_count = int(row.get('Failure Count', 0))

            results.append(EndpointResult(
                name=name,
                request_count=request_count,
                failure_count=failure_count,
                avg_response_time=float(row.get('Average Response Time', 0)),
                min_response_time=float(row.get('Min Response Time', 0)),
                max_response_time=float(row.get('Max Response Time', 0)),
                p50=float(row.get('50%', 0)),
                p95=float(row.get('95%', 0)),
                p99=float(row.get('99%', 0)),
                rps=float(row.get('Requests/s', 0)),
                error_rate=(failure_count / request_count * 100) if request_count > 0 else 0,
            ))

    return results


def get_aggregated_stats(filepath: str) -> Optional[EndpointResult]:
    """Get aggregated stats from CSV."""
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('Name') == 'Aggregated':
                request_count = int(row.get('Request Count', 0))
                failure_count = int(row.get('Failure Count', 0))
                return EndpointResult(
                    name='Aggregated',
                    request_count=request_count,
                    failure_count=failure_count,
                    avg_response_time=float(row.get('Average Response Time', 0)),
                    min_response_time=float(row.get('Min Response Time', 0)),
                    max_response_time=float(row.get('Max Response Time', 0)),
                    p50=float(row.get('50%', 0)),
                    p95=float(row.get('95%', 0)),
                    p99=float(row.get('99%', 0)),
                    rps=float(row.get('Requests/s', 0)),
                    error_rate=(failure_count / request_count * 100) if request_count > 0 else 0,
                )
    return None


def parse_failures_csv(filepath: str) -> List[Dict]:
    """Parse Locust failures CSV file."""
    failures = []
    if not os.path.exists(filepath):
        return failures

    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            failures.append({
                'method': row.get('Method', ''),
                'name': row.get('Name', ''),
                'error': row.get('Error', ''),
                'occurrences': int(row.get('Occurrences', 0)),
            })

    return failures


def detect_anomalies(results: List[EndpointResult], failures: List[Dict]) -> List[Anomaly]:
    """Detect anomalies based on thresholds and rules."""
    anomalies = []

    for result in results:
        # Determine service from endpoint name
        service = "unknown"
        if "market_data" in result.name:
            service = "mcp_market_data"
        elif any(p in result.name for p in ["/stock/", "/market/overview"]):
            service = "mcp_market_data"
        elif "sentiment" in result.name:
            service = "mcp_sentiment"
        elif "news" in result.name or "/earnings" in result.name:
            service = "mcp_news"
        elif "trader" in result.name:
            service = "trader_workflow"

        # Check response time thresholds
        metrics = {
            "p50": result.p50,
            "p95": result.p95,
            "p99": result.p99,
            "error_rate": result.error_rate,
        }

        for anomaly in evaluate_metrics(metrics):
            recommendation = ""
            if anomaly["metric"] == "error_rate":
                recommendation = "Check service logs for exceptions"
            elif anomaly["metric"] in ["p50", "p95", "p99"]:
                recommendation = "Consider caching or optimizing the endpoint"

            anomalies.append(Anomaly(
                severity=anomaly["severity"],
                service=service,
                endpoint=result.name,
                description=anomaly["message"],
                value=anomaly["value"],
                threshold=THRESHOLDS[f"response_time_{anomaly['metric']}"].ok_max
                         if anomaly["metric"] != "error_rate"
                         else THRESHOLDS["error_rate"].ok_max,
                recommendation=recommendation,
            ))

        # Check for timeouts (max response time > 30s)
        if result.max_response_time > 30000:
            anomalies.append(Anomaly(
                severity=Severity.CRITICAL,
                service=service,
                endpoint=result.name,
                description=f"Timeout detected: max response time {result.max_response_time:.0f}ms",
                value=result.max_response_time,
                threshold=30000,
                recommendation="Check external API connectivity",
            ))

    # Check for rate limiting in failures
    for failure in failures:
        if "429" in failure['error'] or "rate limit" in failure['error'].lower():
            anomalies.append(Anomaly(
                severity=Severity.WARNING,
                service="external_api",
                endpoint=failure['name'],
                description=f"Rate limiting detected: {failure['occurrences']} occurrences",
                value=failure['occurrences'],
                threshold=0,
                recommendation="Reduce concurrent users or add request throttling",
            ))
        elif "connection refused" in failure['error'].lower():
            anomalies.append(Anomaly(
                severity=Severity.CRITICAL,
                service="service",
                endpoint=failure['name'],
                description=f"Connection refused: {failure['occurrences']} occurrences",
                value=failure['occurrences'],
                threshold=0,
                recommendation="Verify service is running",
            ))

    return anomalies


def generate_report(
    results: List[EndpointResult],
    aggregated: Optional[EndpointResult],
    failures: List[Dict],
    anomalies: List[Anomaly],
    output_path: str,
    test_profile: str = "unknown",
) -> str:
    """Generate markdown report."""

    report_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Categorize anomalies
    critical = [a for a in anomalies if a.severity == Severity.CRITICAL]
    warnings = [a for a in anomalies if a.severity == Severity.WARNING]

    # Build report
    lines = [
        "═" * 65,
        f"   IB_MCP Load Test Report - {report_date}",
        "═" * 65,
        "",
        "## Résumé Exécutif",
        "",
    ]

    if aggregated:
        error_pct = f"{aggregated.error_rate:.2f}%"
        lines.extend([
            f"- **Total Requests:** {aggregated.request_count:,}",
            f"- **Total Failures:** {aggregated.failure_count:,} ({error_pct})",
            f"- **Avg Response Time:** {aggregated.avg_response_time:.0f}ms",
            f"- **p50 / p95 / p99:** {aggregated.p50:.0f}ms / {aggregated.p95:.0f}ms / {aggregated.p99:.0f}ms",
            f"- **RPS Peak:** {aggregated.rps:.2f}",
            f"- **Test Profile:** {test_profile}",
            "",
        ])

    # Status summary
    if critical:
        lines.append(f"### Status: 🔴 CRITICAL ({len(critical)} issues)")
    elif warnings:
        lines.append(f"### Status: 🟠 WARNING ({len(warnings)} issues)")
    else:
        lines.append("### Status: 🟢 OK - All checks passed")

    lines.append("")

    # Per-service breakdown
    lines.extend([
        "---",
        "",
        "## Par Service",
        "",
    ])

    # Group results by service
    service_results: Dict[str, List[EndpointResult]] = {}
    for result in results:
        service = "unknown"
        if "market_data" in result.name:
            service = "mcp_market_data (5003)"
        elif any(p in result.name for p in ["/stock/", "/market/overview"]):
            service = "mcp_market_data (5003)"
        elif "sentiment" in result.name:
            service = "mcp_sentiment (5004)"
        elif "news" in result.name or "/earnings" in result.name:
            service = "mcp_news (5005)"
        elif "trader" in result.name:
            service = "trader_workflow"

        if service not in service_results:
            service_results[service] = []
        service_results[service].append(result)

    for service, svc_results in sorted(service_results.items()):
        lines.append(f"### {service}")
        lines.append("")
        lines.append("| Endpoint | Requests | Errors | p50 | p95 | p99 | RPS |")
        lines.append("|----------|----------|--------|-----|-----|-----|-----|")

        for r in svc_results:
            error_str = f"{r.error_rate:.1f}%" if r.error_rate > 0 else "0%"
            lines.append(
                f"| {r.name} | {r.request_count} | {error_str} | "
                f"{r.p50:.0f}ms | {r.p95:.0f}ms | {r.p99:.0f}ms | {r.rps:.1f} |"
            )
        lines.append("")

    # Anomalies section
    lines.extend([
        "---",
        "",
        "## Anomalies Détectées",
        "",
    ])

    if critical:
        for a in critical:
            lines.append(f"🔴 **CRITICAL:** [{a.service}] {a.endpoint}")
            lines.append(f"   - {a.description}")
            lines.append(f"   - Valeur: {a.value:.0f}, Seuil: {a.threshold:.0f}")
            lines.append(f"   - Action: {a.recommendation}")
            lines.append("")

    if warnings:
        for a in warnings:
            lines.append(f"🟠 **WARNING:** [{a.service}] {a.endpoint}")
            lines.append(f"   - {a.description}")
            lines.append(f"   - Valeur: {a.value:.0f}, Seuil: {a.threshold:.0f}")
            lines.append(f"   - Action: {a.recommendation}")
            lines.append("")

    if not critical and not warnings:
        lines.append("🟢 **OK:** Aucune anomalie détectée")
        lines.append("")

    # Failures section
    if failures:
        lines.extend([
            "---",
            "",
            "## Erreurs Détaillées",
            "",
            "| Endpoint | Erreur | Occurrences |",
            "|----------|--------|-------------|",
        ])
        for f in failures:
            error_short = f['error'][:50] + "..." if len(f['error']) > 50 else f['error']
            lines.append(f"| {f['name']} | {error_short} | {f['occurrences']} |")
        lines.append("")

    # Recommendations
    lines.extend([
        "---",
        "",
        "## Recommandations",
        "",
    ])

    recommendations = set()
    for a in anomalies:
        if a.recommendation:
            recommendations.add(a.recommendation)

    if recommendations:
        for i, rec in enumerate(recommendations, 1):
            lines.append(f"{i}. {rec}")
    else:
        lines.append("Aucune recommandation - performances nominales.")

    lines.extend([
        "",
        "---",
        "",
        f"*Rapport généré le {report_date}*",
    ])

    report = "\n".join(lines)

    # Write report
    with open(output_path, 'w') as f:
        f.write(report)

    return report


def main():
    parser = argparse.ArgumentParser(description="Analyze Locust load test results")
    parser.add_argument("csv_prefix", help="CSV file prefix (e.g., reports/load_test_baseline_20260206)")
    parser.add_argument("-o", "--output", help="Output report path", default=None)
    parser.add_argument("-p", "--profile", help="Test profile name", default="unknown")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of markdown")

    args = parser.parse_args()

    # Find CSV files
    stats_file = f"{args.csv_prefix}_stats.csv"
    failures_file = f"{args.csv_prefix}_failures.csv"

    if not os.path.exists(stats_file):
        print(f"Error: Stats file not found: {stats_file}")
        sys.exit(1)

    # Parse results
    results = parse_stats_csv(stats_file)
    aggregated = get_aggregated_stats(stats_file)
    failures = parse_failures_csv(failures_file)

    # Detect anomalies
    anomalies = detect_anomalies(results, failures)

    # Generate output path
    if args.output:
        output_path = args.output
    else:
        output_path = f"{args.csv_prefix}_report.md"

    if args.json:
        # JSON output
        output = {
            "timestamp": datetime.now().isoformat(),
            "profile": args.profile,
            "aggregated": {
                "total_requests": aggregated.request_count if aggregated else 0,
                "total_failures": aggregated.failure_count if aggregated else 0,
                "avg_response_time": aggregated.avg_response_time if aggregated else 0,
                "p50": aggregated.p50 if aggregated else 0,
                "p95": aggregated.p95 if aggregated else 0,
                "p99": aggregated.p99 if aggregated else 0,
                "rps": aggregated.rps if aggregated else 0,
            },
            "endpoints": [
                {
                    "name": r.name,
                    "requests": r.request_count,
                    "failures": r.failure_count,
                    "error_rate": r.error_rate,
                    "p50": r.p50,
                    "p95": r.p95,
                    "p99": r.p99,
                    "rps": r.rps,
                }
                for r in results
            ],
            "anomalies": [
                {
                    "severity": a.severity.value,
                    "service": a.service,
                    "endpoint": a.endpoint,
                    "description": a.description,
                    "recommendation": a.recommendation,
                }
                for a in anomalies
            ],
        }
        output_path = output_path.replace(".md", ".json")
        with open(output_path, 'w') as f:
            json.dump(output, f, indent=2)
        print(f"JSON report saved to: {output_path}")
    else:
        # Markdown output
        report = generate_report(
            results, aggregated, failures, anomalies,
            output_path, args.profile
        )
        print(report)
        print(f"\nReport saved to: {output_path}")

    # Exit with error code if critical issues found
    critical_count = len([a for a in anomalies if a.severity == Severity.CRITICAL])
    if critical_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
