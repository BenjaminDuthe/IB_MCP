import time
import logging
import httpx
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sentiment", tags=["CNN Fear & Greed"])

CNN_FG_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; IB_MCP/1.0)",
    "Accept": "application/json",
}

_client = httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=15.0)

# Cache 30min (macro data changes slowly)
_cache = {}
CACHE_TTL_SECONDS = 1800

# Circuit breaker 10min (non-official endpoint)
_circuit = {"open": False, "last_check": 0.0, "cooldown": 600}


def _get_cached(key: str) -> dict | None:
    if key in _cache:
        entry = _cache[key]
        if datetime.now() < entry["expires_at"]:
            return entry["data"]
        del _cache[key]
    return None


def _set_cache(key: str, data: dict) -> None:
    _cache[key] = {
        "data": data,
        "expires_at": datetime.now() + timedelta(seconds=CACHE_TTL_SECONDS),
    }


def _score_to_label(raw_score: float) -> str:
    if raw_score <= 24:
        return "Extreme Fear"
    elif raw_score <= 44:
        return "Fear"
    elif raw_score <= 55:
        return "Neutral"
    elif raw_score <= 74:
        return "Greed"
    else:
        return "Extreme Greed"


@router.get("/feargreed")
async def get_fear_greed():
    """Get CNN Fear & Greed Index: macro market sentiment (0-100)."""
    cached = _get_cached("fear_greed")
    if cached:
        return cached

    if _circuit["open"] and (time.time() - _circuit["last_check"]) < _circuit["cooldown"]:
        remaining = int(_circuit["cooldown"] - (time.time() - _circuit["last_check"]))
        raise HTTPException(
            status_code=503,
            detail=f"CNN Fear & Greed unavailable (circuit breaker). Retry in {remaining}s",
        )

    try:
        resp = await _client.get(CNN_FG_URL)

        if resp.status_code != 200:
            _circuit["open"] = True
            _circuit["last_check"] = time.time()
            raise HTTPException(status_code=503, detail=f"CNN Fear & Greed API returned {resp.status_code}")

        _circuit["open"] = False
        data = resp.json()

        fg_data = data.get("fear_and_greed", {})
        raw_score = fg_data.get("score")

        if raw_score is None:
            raise HTTPException(status_code=502, detail="CNN Fear & Greed response missing score")

        raw_score = float(raw_score)
        sentiment_score = round((raw_score - 50) / 50, 4)
        label = _score_to_label(raw_score)

        result = {
            "source": "fear_greed",
            "raw_score": round(raw_score, 1),
            "sentiment_score": sentiment_score,
            "label": label,
            "timestamp": fg_data.get("timestamp", datetime.now().isoformat()),
            "previous_close": fg_data.get("previous_close"),
            "one_week_ago": fg_data.get("previous_1_week"),
            "one_month_ago": fg_data.get("previous_1_month"),
        }
        _set_cache("fear_greed", result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        _circuit["open"] = True
        _circuit["last_check"] = time.time()
        logger.error(f"Fear & Greed error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
