FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY . /app/telegram_bot

ENV PYTHONPATH=/app
ENV UV_CACHE_DIR=/tmp/uv-cache

RUN uv sync

EXPOSE 5010

CMD ["uv", "run", "--", "python", "/app/telegram_bot/bot.py"]
