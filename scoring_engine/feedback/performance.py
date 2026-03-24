"""Weekly performance reports."""

import logging

from scoring_engine.feedback.tracker import compute_signal_accuracy
from scoring_engine.influx_writer import write_points, _escape_tag
from scoring_engine.alerter import alert_daily_summary

logger = logging.getLogger(__name__)


async def generate_weekly_performance() -> dict:
    """Compute weekly performance metrics and write to InfluxDB."""
    accuracy = await compute_signal_accuracy()

    # Write to InfluxDB
    import time
    ts = int(time.time())
    fields = [
        f"win_rate={accuracy['win_rate']}",
        f"total_signals={accuracy['total_signals']}i",
        f"evaluated={accuracy['evaluated']}i",
        f"profitable={accuracy['profitable']}i",
        f"avg_return_pct={accuracy['avg_return_pct']}",
    ]
    line = f"performance,period=weekly {','.join(fields)} {ts}"
    await write_points([line])

    return accuracy


async def generate_performance_report() -> str:
    """Human-readable weekly performance report."""
    perf = await generate_weekly_performance()

    if perf["total_signals"] == 0:
        return "📊 Pas encore de signaux pour calculer la performance."

    lines = [
        f"📊 **Performance Hebdo**\n",
        f"Signaux totaux: {perf['total_signals']}",
        f"Évalués: {perf['evaluated']}",
        f"Win rate: **{perf['win_rate']:.0f}%**",
        f"Rendement moyen: {perf['avg_return_pct']:+.1f}%",
        "",
    ]

    if perf["signals"]:
        lines.append("Top signaux récents:")
        for s in perf["signals"][:5]:
            emoji = "✅" if s["profitable"] else "❌"
            lines.append(
                f"  {emoji} {s['ticker']}: ${s['signal_price']:.2f} → ${s['current_price']:.2f} ({s['return_pct']:+.1f}%)"
            )

    report = "\n".join(lines)
    await alert_daily_summary(report)
    return report
