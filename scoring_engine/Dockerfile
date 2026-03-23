FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    fastapi==0.115.* \
    uvicorn[standard]==0.34.* \
    httpx==0.28.* \
    apscheduler==3.11.*

COPY . /app/scoring_engine/

EXPOSE 5030

CMD ["uvicorn", "scoring_engine.server:app", "--host", "0.0.0.0", "--port", "5030"]
