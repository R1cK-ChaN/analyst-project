from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst.engine.live_types import AgentTool
from analyst.mcp.bridge import ClaudeCodeMcpConfig
from analyst.mcp.server import AnalystMcpServer


class ClaudeCodeMcpConfigTest(unittest.TestCase):
    def test_to_json_builds_stdio_server_config(self) -> None:
        config = ClaudeCodeMcpConfig(
            tool_names=("fetch_live_news", "get_vix_regime"),
            db_path="/tmp/analyst-test.db",
        )

        payload = config.to_json()
        server = payload["mcpServers"]["analyst"]

        self.assertEqual(server["args"], ["-m", "analyst.mcp.server"])
        self.assertEqual(server["env"]["ANALYST_MCP_TOOL_NAMES"], "fetch_live_news,get_vix_regime")
        self.assertEqual(server["env"]["ANALYST_MCP_DB_PATH"], "/tmp/analyst-test.db")
        self.assertIn("src", server["env"]["PYTHONPATH"])


class AnalystMcpServerTest(unittest.TestCase):
    def test_initialize_tools_list_and_call(self) -> None:
        tool = AgentTool(
            name="fetch_live_news",
            description="Fetch news",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            handler=lambda arguments: {"status": "ok", "echo": arguments},
        )
        server = AnalystMcpServer(tools=[tool])

        initialize = server.handle_request(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}
        )
        self.assertEqual(initialize["result"]["protocolVersion"], "2025-06-18")
        self.assertIn("tools", initialize["result"]["capabilities"])

        listing = server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        self.assertEqual(listing["result"]["tools"][0]["name"], "fetch_live_news")
        self.assertEqual(listing["result"]["tools"][0]["inputSchema"]["type"], "object")

        called = server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "fetch_live_news", "arguments": {"query": "rates"}},
            }
        )
        self.assertFalse(called["result"]["isError"])
        rendered = called["result"]["content"][0]["text"]
        parsed = json.loads(rendered)
        self.assertEqual(parsed["echo"], {"query": "rates"})

    def test_unknown_tool_returns_error_payload(self) -> None:
        server = AnalystMcpServer(tools=[])

        result = server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {"name": "missing_tool", "arguments": {}},
            }
        )

        self.assertTrue(result["result"]["isError"])
        self.assertIn("Unknown tool", result["result"]["content"][0]["text"])
