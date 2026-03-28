FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    fastapi==0.115.* \
    uvicorn[standard]==0.34.* \
    httpx==0.28.* \
    apscheduler==3.11.* \
    numpy==2.2.* \
    pandas==2.2.* \
    fastmcp==2.10.3 \
    "pydantic>=2.11,<2.12"

COPY . /app/scoring_engine/

EXPOSE 5030

CMD ["uvicorn", "scoring_engine.server:app", "--host", "0.0.0.0", "--port", "5030"]
