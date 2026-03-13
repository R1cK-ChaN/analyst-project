from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst.runtime.capabilities import build_capability_tools, get_capability_surface
from analyst.storage import SQLiteEngineStore


class CapabilityRegistryTest(unittest.TestCase):
    def test_surface_matrix_distinguishes_companion_and_user_chat_mcp_scope(self) -> None:
        companion = get_capability_surface("companion")
        user_chat = get_capability_surface("user_chat")

        self.assertEqual(companion.native_tool_names, ("WebSearch", "WebFetch"))
        self.assertEqual(user_chat.native_tool_names, ("WebSearch", "WebFetch"))
        self.assertNotIn("get_portfolio_risk", companion.shared_mcp_tool_names)
        self.assertIn("get_portfolio_risk", user_chat.shared_mcp_tool_names)
        self.assertIn("research_lookup", user_chat.sub_agent_names)

    def test_user_chat_surface_builds_declared_tools_and_sub_agents(self) -> None:
        engine = MagicMock()
        engine.get_regime_summary.return_value = MagicMock(body_markdown="regime")
        engine.build_premarket_briefing.return_value = MagicMock(body_markdown="premarket")
        engine.get_calendar.return_value = []

        with tempfile.TemporaryDirectory() as tmpdir:
            store = SQLiteEngineStore(db_path=Path(tmpdir) / "test.db")
            tools = build_capability_tools(
                "user_chat",
                engine=engine,
                store=store,
                provider=MagicMock(),
            )

        tool_names = {tool.name for tool in tools}
        self.assertIn("search_research_notes", tool_names)
        self.assertIn("research_lookup", tool_names)
        self.assertIn("portfolio_analyst", tool_names)

    def test_companion_surface_builds_declared_sub_agent_when_provider_present(self) -> None:
        tools = build_capability_tools(
            "companion",
            store=MagicMock(),
            provider=MagicMock(),
        )
        tool_names = {tool.name for tool in tools}
        self.assertIn("research_agent", tool_names)


if __name__ == "__main__":
    unittest.main()
