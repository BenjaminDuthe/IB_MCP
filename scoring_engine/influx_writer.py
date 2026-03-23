"""InfluxDB 1.6 writer using line protocol over HTTP."""

import logging
import time

import httpx

from scoring_engine.config import (
    INFLUXDB_URL,
    INFLUXDB_DATABASE,
    INFLUXDB_USER,
    INFLUXDB_PASSWORD,
)

logger = logging.getLogger(__name__)

_client = httpx.AsyncClient(timeout=10.0)


def _escape_tag(v: str) -> str:
    return v.replace(" ", "\\ ").replace(",", "\\,").replace("=", "\\=")


def _escape_field_str(v: str) -> str:
    return v.replace('"', '\\"')


async def write_points(lines: list[str]) -> bool:
    """Write line protocol points to InfluxDB."""
    if not lines:
        return True
    body = "\n".join(lines)
    params = {"db": INFLUXDB_DATABASE, "precision": "s"}
    if INFLUXDB_USER:
        params["u"] = INFLUXDB_USER
        params["p"] = INFLUXDB_PASSWORD
    try:
        resp = await _client.post(f"{INFLUXDB_URL}/write", params=params, content=body)
        if resp.status_code == 204:
            return True
        logger.error("InfluxDB write error %d: %s", resp.status_code, resp.text[:200])
        return False
    except Exception as e:
        logger.error("InfluxDB write failed: %s", e)
        return False


async def write_technicals(ticker: str, market: str, data: dict) -> bool:
    ma = data.get("moving_averages", {})
    macd = data.get("macd", {}) or {}
    ts = int(time.time())
    fields = []
    for k, v in [
        ("price", data.get("price")),
        ("rsi_14", data.get("rsi_14")),
        ("macd_histogram", macd.get("histogram")),
        ("sma_20", ma.get("sma_20")),
        ("sma_50", ma.get("sma_50")),
        ("sma_200", ma.get("sma_200")),
        ("atr_14", data.get("atr_14")),
        ("trend_5d", data.get("trend_5d")),
        ("volume_relative", (data.get("volume") or {}).get("relative")),
    ]:
        if v is not None:
            fields.append(f"{k}={v}")
    trend = ma.get("trend", "neutral")
    fields.append(f'ma_trend="{_escape_field_str(trend)}"')
    if not fields:
        return True
    line = f"technicals,ticker={_escape_tag(ticker)},market={market} {','.join(fields)} {ts}"
    return await write_points([line])


async def write_sentiment(ticker: str, source: str, score: float, label: str) -> bool:
    ts = int(time.time())
    line = (
        f'sentiment,ticker={_escape_tag(ticker)},source={_escape_tag(source)} '
        f'score={score},label="{_escape_field_str(label)}" {ts}'
    )
    return await write_points([line])


async def write_scoring(ticker: str, market: str, score_data: dict, llm: dict) -> bool:
    ts = int(time.time())
    filters = score_data.get("filters", {})
    fields = [
        f"score={score_data['score']}i",
        f"filter_sma20={'1i' if filters.get('price_above_sma20') else '0i'}",
        f"filter_trend5d={'1i' if filters.get('trend_5d_positive') else '0i'}",
        f"filter_rsi={'1i' if filters.get('rsi_below_threshold') else '0i'}",
        f"filter_sma200={'1i' if filters.get('price_above_sma200') else '0i'}",
        f"filter_atr={'1i' if filters.get('atr_relative_ok') else '0i'}",
        f'llm_verdict="{_escape_field_str(llm.get("verdict", "HOLD"))}"',
        f"llm_confidence={llm.get('confidence', 0)}i",
    ]
    line = f"scoring,ticker={_escape_tag(ticker)},market={market} {','.join(fields)} {ts}"
    return await write_points([line])


async def write_signal(ticker: str, action: str, confidence: int, price: float, score: int, summary: str) -> bool:
    ts = int(time.time())
    fields = [
        f"confidence={confidence}i",
        f"price={price}",
        f"score={score}i",
        f'reason="{_escape_field_str(summary[:500])}"',
    ]
    line = f"signals,ticker={_escape_tag(ticker)},action={_escape_tag(action)},source=auto {','.join(fields)} {ts}"
    return await write_points([line])


async def write_pipeline_status(pipeline: str, duration: float, tickers: int, signals: int, errors: int) -> bool:
    ts = int(time.time())
    fields = [
        f"duration_seconds={duration:.2f}",
        f"tickers_processed={tickers}i",
        f"signals_generated={signals}i",
        f"errors={errors}i",
    ]
    line = f"pipeline_status,pipeline={_escape_tag(pipeline)} {','.join(fields)} {ts}"
    return await write_points([line])


async def write_analyst_reports(ticker: str, reports) -> bool:
    """Write analyst agent reports to InfluxDB."""
    ts = int(time.time())
    lines = []
    for r in reports:
        fields = [
            f"score={r.score}",
            f"confidence={r.confidence}i",
        ]
        line = f"analyst_report,ticker={_escape_tag(ticker)},agent={_escape_tag(r.agent_name)} {','.join(fields)} {ts}"
        lines.append(line)
    return await write_points(lines)


async def write_debate(ticker: str, debate: dict) -> bool:
    """Write debate result to InfluxDB."""
    ts = int(time.time())
    fields = [
        f'verdict="{_escape_field_str(debate.get("verdict", "HOLD"))}"',
        f"confidence={debate.get('confidence', 0)}i",
        f"bull_strength={debate.get('bull_strength', 0)}i",
        f"bear_strength={debate.get('bear_strength', 0)}i",
        f'key_factor="{_escape_field_str(debate.get("key_factor", "")[:200])}"',
    ]
    line = f"debate,ticker={_escape_tag(ticker)} {','.join(fields)} {ts}"
    return await write_points([line])
