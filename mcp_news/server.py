import os
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


@asynccontextmanager
async def lifespan(app):
    async with mcp_app.lifespan(app):
        yield


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
    uvicorn.run(app, host=host, port=port, log_level="info")
