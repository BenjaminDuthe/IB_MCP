import os
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


@asynccontextmanager
async def lifespan(app):
    async with mcp_app.lifespan(app):
        yield


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
    return {"status": "ok", "service": "mcp-market-data"}


app.mount("/mcp", mcp_app)

if __name__ == "__main__":
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "5003"))
    uvicorn.run(app, host=host, port=port, log_level="info")
