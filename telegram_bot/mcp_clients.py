import os
import json
import logging
import httpx
from typing import Any

logger = logging.getLogger(__name__)

# MCP server configurations (name -> url)
MCP_SERVERS = {
    "ib": {
        "url": os.environ.get("MCP_IB_URL", "http://mcp_server:5002/mcp"),
        "prefix": "ib",
    },
    "market_data": {
        "url": os.environ.get("MCP_MARKET_DATA_URL", "http://mcp_market_data:5003/mcp/mcp/"),
        "prefix": "mktdata",
    },
    "sentiment": {
        "url": os.environ.get("MCP_SENTIMENT_URL", "http://mcp_sentiment:5004/mcp/mcp/"),
        "prefix": "sentiment",
    },
    "news": {
        "url": os.environ.get("MCP_NEWS_URL", "http://mcp_news:5005/mcp/mcp/"),
        "prefix": "news",
    },
}


def _parse_sse_response(sse_text: str) -> dict | None:
    """Parse an SSE response and return the first JSON-RPC result."""
    for line in sse_text.strip().split("\n"):
        if line.startswith("data: "):
            try:
                return json.loads(line[6:])
            except json.JSONDecodeError:
                continue
    return None


class MCPSession:
    """Manages an MCP session with a single server (initialize + session ID)."""

    def __init__(self, url: str):
        self.url = url
        self.session_id: str | None = None
        self._request_id = 0

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _headers(self) -> dict:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        return h

    async def _post(self, client: httpx.AsyncClient, payload: dict) -> dict:
        """Send a JSON-RPC request and parse the response."""
        resp = await client.post(self.url, json=payload, headers=self._headers())
        resp.raise_for_status()

        # Capture session ID from response headers
        sid = resp.headers.get("mcp-session-id")
        if sid:
            self.session_id = sid

        content_type = resp.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            data = _parse_sse_response(resp.text)
            if data is None:
                raise RuntimeError(f"Empty SSE response from {self.url}")
            return data
        else:
            return resp.json()

    async def initialize(self, client: httpx.AsyncClient):
        """Send MCP initialize handshake."""
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "telegram-bot", "version": "0.1"},
            },
        }
        result = await self._post(client, payload)
        if "error" in result:
            raise RuntimeError(f"MCP initialize error: {result['error']}")
        logger.debug(f"MCP session initialized: {self.session_id}")

        # Send initialized notification (required by MCP spec before tools/list)
        notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        await client.post(self.url, json=notif, headers=self._headers())

    async def list_tools(self, client: httpx.AsyncClient) -> list[dict]:
        """List available tools after initialization."""
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/list",
        }
        data = await self._post(client, payload)
        if "error" in data:
            raise RuntimeError(f"MCP tools/list error: {data['error']}")
        return data.get("result", {}).get("tools", [])

    async def call_tool(self, client: httpx.AsyncClient, name: str, arguments: dict) -> Any:
        """Call a tool by name."""
        payload = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        data = await self._post(client, payload)
        if "error" in data:
            raise RuntimeError(f"MCP tool error: {data['error']}")
        return data.get("result", {})


class MCPClientManager:
    """Manages MCP sessions to multiple servers."""

    def __init__(self):
        self._tools: dict[str, dict] = {}  # prefixed_name -> {server, tool_def, session}
        self._server_tools: dict[str, list] = {}  # server_name -> [tool_defs]
        self._sessions: dict[str, MCPSession] = {}  # server_name -> session

    async def discover_tools(self):
        """Connect to each MCP server, initialize session, and discover tools."""
        self._tools.clear()
        self._server_tools.clear()
        self._sessions.clear()

        for server_name, config in MCP_SERVERS.items():
            url = config["url"]
            prefix = config["prefix"]
            try:
                session = MCPSession(url)
                async with httpx.AsyncClient(timeout=30) as client:
                    await session.initialize(client)
                    tools = await session.list_tools(client)

                self._sessions[server_name] = session
                self._server_tools[server_name] = tools

                for tool in tools:
                    prefixed_name = f"{prefix}_{tool['name']}"
                    self._tools[prefixed_name] = {
                        "server": server_name,
                        "original_name": tool["name"],
                        "definition": tool,
                    }
                logger.info(f"Discovered {len(tools)} tools from {server_name} ({url})")
            except Exception as e:
                logger.error(f"Failed to discover tools from {server_name} ({url}): {e}")
                self._server_tools[server_name] = []

    async def call_tool(self, prefixed_name: str, arguments: dict) -> Any:
        """Call a tool on the appropriate MCP server."""
        tool_info = self._tools.get(prefixed_name)
        if not tool_info:
            raise ValueError(f"Unknown tool: {prefixed_name}")

        server_name = tool_info["server"]
        original_name = tool_info["original_name"]
        session = self._sessions.get(server_name)

        if not session:
            raise RuntimeError(f"No active session for server: {server_name}")

        async with httpx.AsyncClient(timeout=60) as client:
            return await session.call_tool(client, original_name, arguments)

    def get_claude_tool_definitions(self) -> list[dict]:
        """Convert MCP tools to Claude API tool definitions with namespaced names."""
        claude_tools = []
        for prefixed_name, tool_info in self._tools.items():
            tool_def = tool_info["definition"]
            claude_tools.append({
                "name": prefixed_name,
                "description": tool_def.get("description", ""),
                "input_schema": tool_def.get("inputSchema", {"type": "object", "properties": {}}),
            })
        return claude_tools

    def get_server_status(self) -> dict[str, dict]:
        """Get status of all MCP server connections."""
        status = {}
        for server_name, config in MCP_SERVERS.items():
            tools = self._server_tools.get(server_name, [])
            session = self._sessions.get(server_name)
            status[server_name] = {
                "url": config["url"],
                "prefix": config["prefix"],
                "tools_count": len(tools),
                "connected": len(tools) > 0,
                "session_id": session.session_id if session else None,
            }
        return status
