import os
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastmcp import FastMCP

from mcp_sentiment.tools.reddit import router as reddit_router
from mcp_sentiment.tools.stocktwits import router as stocktwits_router
from mcp_sentiment.tools.combined import router as combined_router

_tool_app = FastAPI()
_tool_app.include_router(reddit_router)
_tool_app.include_router(stocktwits_router)
_tool_app.include_router(combined_router)

mcp = FastMCP.from_fastapi(app=_tool_app)
mcp_app = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(app):
    async with mcp_app.lifespan(app):
        yield


app = FastAPI(
    title="Sentiment Analysis MCP",
    description="MCP server providing social sentiment analysis from Reddit and StockTwits.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(reddit_router)
app.include_router(stocktwits_router)
app.include_router(combined_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "mcp-sentiment"}


app.mount("/mcp", mcp_app)

if __name__ == "__main__":
    host = os.environ.get("MCP_HOST", "0.0.0.0")
    port = int(os.environ.get("MCP_PORT", "5004"))
    uvicorn.run(app, host=host, port=port, log_level="info")
