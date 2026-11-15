"""Minimal MCP stdio client used by ADK nodes and CrewAI tools."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = PROJECT_ROOT / "mcp_servers"
AUDIT_FILE = PROJECT_ROOT / "data" / "mcp_audit.jsonl"


class MCPToolError(RuntimeError):
    """Raised when an MCP server rejects a call or returns invalid content."""


def mcp_enabled() -> bool:
    return os.environ.get("MCP_ENABLED", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _server_path(server: str) -> Path:
    path = (SERVER_DIR / server).resolve()
    if path.parent != SERVER_DIR.resolve():
        raise ValueError("Unknown MCP server")
    if not path.is_file():
        raise FileNotFoundError(f"MCP server not found: {server}")
    return path


def _safe_arguments(arguments: Dict[str, Any]) -> Dict[str, Any]:
    safe: Dict[str, Any] = {}
    for key, value in arguments.items():
        if key == "path":
            safe[key] = Path(str(value)).name
        elif isinstance(value, str):
            safe[key] = value[:200]
        else:
            safe[key] = value
    return safe


def _audit(
    *,
    server: str,
    tool: str,
    arguments: Dict[str, Any],
    status: str,
    duration_ms: float,
    error: str | None = None,
) -> None:
    try:
        AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_FILE.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "server": server,
                        "tool": tool,
                        "arguments": _safe_arguments(arguments),
                        "status": status,
                        "duration_ms": round(duration_ms, 2),
                        "error": error,
                    },
                    default=str,
                )
                + "\n"
            )
    except OSError:
        pass


def _decode_result(result: Any) -> Any:
    if getattr(result, "isError", False):
        raise MCPToolError("MCP server returned an error result")
    structured = getattr(result, "structuredContent", None)
    if structured not in (None, {}, []):
        return structured
    parts = []
    for content in getattr(result, "content", []) or []:
        text = getattr(content, "text", None)
        if text:
            parts.append(text)
    raw = "\n".join(parts).strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        return raw


async def call_tool_async(server: str, tool: str, arguments: Dict[str, Any]) -> Any:
    """Call a tool over the real MCP stdio protocol."""
    if not mcp_enabled():
        raise MCPToolError("MCP is disabled by MCP_ENABLED")
    from services.tracing import span, update

    started = time.perf_counter()
    with span(
        "mcp.tool",
        as_type="tool",
        input={"server": server, "tool": tool, "arguments": _safe_arguments(arguments)},
        metadata={"server": server},
    ) as observation:
        try:
            server_path = _server_path(server)
            params = StdioServerParameters(
                command=sys.executable,
                args=[str(server_path)],
                cwd=str(PROJECT_ROOT),
                env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT)},
            )
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(tool, arguments)
            decoded = _decode_result(result)
        except Exception as exc:
            duration = (time.perf_counter() - started) * 1000
            _audit(
                server=server,
                tool=tool,
                arguments=arguments,
                status="error",
                duration_ms=duration,
                error=f"{type(exc).__name__}: {exc}",
            )
            update(
                observation,
                level="ERROR",
                status_message=f"{type(exc).__name__}: {exc}",
                metadata={"duration_ms": round(duration, 2)},
            )
            raise
        duration = (time.perf_counter() - started) * 1000
        _audit(
            server=server,
            tool=tool,
            arguments=arguments,
            status="success",
            duration_ms=duration,
        )
        update(
            observation,
            output={"result_type": type(decoded).__name__},
            metadata={"duration_ms": round(duration, 2)},
        )
        return decoded


def call_tool(server: str, tool: str, arguments: Dict[str, Any]) -> Any:
    """Synchronous wrapper that is safe inside or outside an event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(call_tool_async(server, tool, arguments))

    ctx = contextvars.copy_context()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            ctx.run,
            asyncio.run,
            call_tool_async(server, tool, arguments),
        )
        return future.result()
