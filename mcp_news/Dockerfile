FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY . /app/mcp_news

ENV PYTHONPATH=/app
ENV UV_CACHE_DIR=/tmp/uv-cache

RUN uv sync

EXPOSE 5005

CMD ["uv", "run", "--", "python", "/app/mcp_news/server.py"]
