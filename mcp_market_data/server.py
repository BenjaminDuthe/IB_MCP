import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastmcp import FastMCP

from mcp_market_data.tools.stock import router as stock_router
from mcp_market_data.tools.fundamentals import router as fundamentals_router
from mcp_market_data.tools.history import router as history_router
from mcp_market_data.tools.overview import router as overview_router

# Create MCP from a temporary FastAPI to extract tools
_tool_app = FastAPI()
_tool_app.include_router(stock_router)
_tool_app.include_router(fundamentals_router)
_tool_app.include_router(history_router)
_tool_app.include_router(overview_router)

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
    title="Market Data MCP",
    description="MCP server providing market data via yfinance.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(stock_router)
app.include_router(fundamentals_router)
app.include_router(history_router)
app.include_router(overview_router)


@app.get("/health")
async def health():
    pool_info = {
        "threads_active": _executor._work_queue.qsize(),
        "max_workers": _executor._max_workers,
    }
    return {"status": "ok", "service": "mcp-market-data", "thread_pool": pool_info}


app.mount("/mcp", mcp_app)

if __name__ == "__main__":
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "5003"))
    workers = int(os.environ.get("MCP_WORKERS", "1"))
    if workers > 1:
        uvicorn.run("mcp_market_data.server:app", host=host, port=port, workers=workers, log_level="info")
    else:
        uvicorn.run(app, host=host, port=port, log_level="info")
