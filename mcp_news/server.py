import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastmcp import FastMCP

from mcp_news.tools.finnhub_news import router as finnhub_router
from mcp_news.tools.earnings import router as earnings_router
from mcp_news.tools.rss import router as rss_router

_tool_app = FastAPI()
_tool_app.include_router(finnhub_router)
_tool_app.include_router(earnings_router)
_tool_app.include_router(rss_router)

mcp = FastMCP.from_fastapi(app=_tool_app)
mcp_app = mcp.streamable_http_app()


_executor = ThreadPoolExecutor(
    max_workers=int(os.environ.get("THREAD_POOL_SIZE", "100"))
)


@asynccontextmanager
async def lifespan(app):
    loop = asyncio.get_running_loop()
    loop.set_default_executor(_executor)
    async with mcp_app.lifespan(app):
        yield
    _executor.shutdown(wait=False)


app = FastAPI(
    title="News MCP",
    description="MCP server providing financial news from Finnhub and RSS feeds.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(finnhub_router)
app.include_router(earnings_router)
app.include_router(rss_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "mcp-news"}


app.mount("/mcp", mcp_app)

if __name__ == "__main__":
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "5005"))
    workers = int(os.environ.get("MCP_WORKERS", "1"))
    if workers > 1:
        uvicorn.run("mcp_news.server:app", host=host, port=port, workers=workers, log_level="info")
    else:
        uvicorn.run(app, host=host, port=port, log_level="info")
