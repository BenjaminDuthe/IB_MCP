"""Base classes for analyst agents + shared Ollama client."""

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict

import httpx

from scoring_engine.config import OLLAMA_URL, OLLAMA_MODEL

logger = logging.getLogger(__name__)


@dataclass
class AnalystReport:
    agent_name: str
    ticker: str
    score: float  # -1.0 to +1.0
    confidence: int  # 0-100
    summary: str
    metrics: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


class OllamaClient:
    """Reusable Ollama inference client with retry + JSON parsing."""

    def __init__(self, url: str = OLLAMA_URL, model: str = OLLAMA_MODEL):
        self.url = url
        self.model = model
        self._client = httpx.AsyncClient(timeout=120.0)

    async def generate(
        self, system_prompt: str, user_prompt: str,
        max_tokens: int = 200, temperature: float = 0.3,
    ) -> dict:
        """Call Ollama and return parsed JSON or raw text fallback."""
        try:
            resp = await self._client.post(
                f"{self.url}/api/generate",
                json={
                    "model": self.model,
                    "system": system_prompt,
                    "prompt": user_prompt,
                    "stream": False,
                    "options": {"num_predict": max_tokens, "temperature": temperature},
                },
            )
            resp.raise_for_status()
            raw = (resp.json().get("response") or "").strip()

            # Try JSON parse
            text = raw
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": raw, "_parse_error": True}
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            logger.error("Ollama generate failed: %s", e)
            return {"raw": "", "_error": str(e)}
        except Exception as e:
            logger.error("Ollama unexpected error: %s", e)
            return {"raw": "", "_error": str(e)}


class AnalystAgent(ABC):
    """Base class for all analyst agents."""

    name: str = "base"

    @abstractmethod
    async def analyze(self, ticker: str, context: dict) -> AnalystReport:
        ...
