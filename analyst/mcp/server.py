from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from analyst.engine.live_types import AgentTool
from analyst.env import get_env_value

from .shared_tools import build_shared_mcp_tools, validate_shared_mcp_tool_names

logger = logging.getLogger(__name__)

_SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")


@dataclass
class AnalystMcpServer:
    tools: list[AgentTool]
    server_name: str = "analyst-product-tools"
    server_version: str = "0.1.0"

    def __post_init__(self) -> None:
        self._tools_by_name = {tool.name: tool for tool in self.tools}

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        method = str(request.get("method", ""))
        request_id = request.get("id")
        params = request.get("params")
        if not isinstance(params, dict):
            params = {}

        if method == "notifications/initialized":
            return None
        if method == "initialize":
            return self._success(
                request_id,
                {
                    "protocolVersion": self._select_protocol_version(str(params.get("protocolVersion", "")).strip()),
                    "capabilities": {
                        "tools": {
                            "listChanged": False,
                        }
                    },
                    "serverInfo": {
                        "name": self.server_name,
                        "version": self.server_version,
                    },
                },
            )
        if method == "ping":
            return self._success(request_id, {})
        if method == "tools/list":
            return self._success(
                request_id,
                {
                    "tools": [
                        {
                            "name": tool.name,
                            "description": tool.description,
                            "inputSchema": tool.parameters,
                        }
                        for tool in self.tools
                    ]
                },
            )
        if method == "tools/call":
            tool_name = str(params.get("name", "")).strip()
            arguments = params.get("arguments", {})
            if not isinstance(arguments, dict):
                return self._error(request_id, -32602, "Tool arguments must be an object.")
            tool = self._tools_by_name.get(tool_name)
            if tool is None:
                return self._success(
                    request_id,
                    {
                        "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
                        "isError": True,
                    },
                )
            try:
                result = tool.handler(arguments)
            except Exception as exc:  # pragma: no cover - defensive guard
                logger.exception("MCP tool %s failed", tool_name)
                return self._success(
                    request_id,
                    {
                        "content": [{"type": "text", "text": f"Tool {tool_name} failed: {exc}"}],
                        "isError": True,
                    },
                )
            is_error = isinstance(result, dict) and bool(result.get("error"))
            return self._success(
                request_id,
                {
                    "content": [{"type": "text", "text": self._render_tool_result(result)}],
                    "isError": is_error,
                },
            )
        return self._error(request_id, -32601, f"Method not found: {method}")

    def _select_protocol_version(self, requested: str) -> str:
        if requested in _SUPPORTED_PROTOCOL_VERSIONS:
            return requested
        return _SUPPORTED_PROTOCOL_VERSIONS[0]

    def _render_tool_result(self, result: Any) -> str:
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)

    def _success(self, request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _error(self, request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def build_server(
    *,
    tool_names: tuple[str, ...],
    db_path: str | Path | None = None,
) -> AnalystMcpServer:
    return AnalystMcpServer(
        tools=build_shared_mcp_tools(tool_names=tool_names, db_path=db_path),
    )


def run_stdio_server(server: AnalystMcpServer) -> int:
    stdin = sys.stdin
    stdout = sys.stdout
    for raw_line in stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Ignoring non-JSON MCP line: %r", line[:200])
            continue
        if not isinstance(request, dict):
            continue
        response = server.handle_request(request)
        if response is None:
            continue
        stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
        stdout.flush()
    return 0


def main() -> int:
    tool_names = validate_shared_mcp_tool_names(
        tuple(
            item.strip()
            for item in get_env_value("ANALYST_MCP_TOOL_NAMES", default="").split(",")
            if item.strip()
        )
    )
    db_path_raw = get_env_value("ANALYST_MCP_DB_PATH", default="").strip()
    db_path = Path(db_path_raw) if db_path_raw else None
    server = build_server(tool_names=tool_names, db_path=db_path)
    return run_stdio_server(server)


if __name__ == "__main__":
    raise SystemExit(main())
