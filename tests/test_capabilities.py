from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from analyst.engine.live_provider import ClaudeCodeConfig, ClaudeCodeProvider
from analyst.runtime.capabilities import build_capability_tools, get_capability_surface


class CapabilityRegistryTest(unittest.TestCase):
    def test_companion_surface_has_expected_native_and_mcp_tools(self) -> None:
        companion = get_capability_surface("companion")
        self.assertEqual(companion.native_tool_names, ("WebSearch", "WebFetch"))
        self.assertIn("generate_image", companion.shared_mcp_tool_names)

    def test_companion_surface_builds_tools_when_provider_present(self) -> None:
        tools = build_capability_tools(
            "companion",
            store=MagicMock(),
            provider=MagicMock(),
        )
        tool_names = {tool.name for tool in tools}
        self.assertIn("generate_image", tool_names)


class NativeModeCapabilityTest(unittest.TestCase):
    """Tests for Claude Code native mode capability surface."""

    def _make_cc_provider(self) -> ClaudeCodeProvider:
        return ClaudeCodeProvider(
            ClaudeCodeConfig(oauth_token="token", model="sonnet"),
            runner=MagicMock(),
        )

    def test_mcp_tool_names_include_media_tools(self) -> None:
        companion = get_capability_surface("companion")
        self.assertIn("generate_image", companion.shared_mcp_tool_names)

    def test_new_mcp_tools_appear_in_shared_tool_specs(self) -> None:
        from analyst.mcp.shared_tools import SHARED_MCP_TOOL_SPECS

        self.assertIn("generate_image", SHARED_MCP_TOOL_SPECS)
        self.assertIn("generate_live_photo", SHARED_MCP_TOOL_SPECS)
        self.assertIn("sync_portfolio_from_broker", SHARED_MCP_TOOL_SPECS)

    def test_companion_surface_skips_web_search_for_claude_code(self) -> None:
        cc_provider = self._make_cc_provider()
        tools = build_capability_tools(
            "companion",
            store=MagicMock(),
            provider=cc_provider,
        )
        tool_names = {tool.name for tool in tools}
        self.assertNotIn("web_search", tool_names)

class MediaExtractionFromEventsTest(unittest.TestCase):
    """Tests for _extract_media_from_events (stream-json MCP tool results)."""

    def test_extracts_image_from_mcp_tool_result(self) -> None:
        from analyst.runtime.chat import _extract_media_from_events

        events = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_name": "analyst__generate_image",
                            "content": json.dumps({
                                "status": "ok",
                                "image_path": "/tmp/test_image.jpg",
                            }),
                        }
                    ]
                },
            }
        ]

        media = _extract_media_from_events(events)
        self.assertEqual(len(media), 1)
        self.assertEqual(media[0].kind, "photo")
        self.assertEqual(media[0].url, "/tmp/test_image.jpg")

    def test_extracts_video_from_live_photo_tool_result(self) -> None:
        from analyst.runtime.chat import _extract_media_from_events

        events = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_name": "analyst__generate_live_photo",
                            "content": json.dumps({
                                "status": "ok",
                                "delivery_video_path": "/tmp/video.mp4",
                                "asset_id": "abc123",
                            }),
                        }
                    ]
                },
            }
        ]

        media = _extract_media_from_events(events)
        self.assertEqual(len(media), 1)
        self.assertEqual(media[0].kind, "video")
        self.assertEqual(media[0].url, "/tmp/video.mp4")
        self.assertEqual(media[0].metadata["asset_id"], "abc123")

    def test_handles_unprefixed_tool_names(self) -> None:
        from analyst.runtime.chat import _extract_media_from_events

        events = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_name": "generate_image",
                            "content": json.dumps({
                                "status": "ok",
                                "image_url": "https://cdn.example.com/img.jpg",
                            }),
                        }
                    ]
                },
            }
        ]

        media = _extract_media_from_events(events)
        self.assertEqual(len(media), 1)
        self.assertEqual(media[0].url, "https://cdn.example.com/img.jpg")

    def test_skips_non_media_tool_results(self) -> None:
        from analyst.runtime.chat import _extract_media_from_events

        events = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_name": "analyst__fetch_live_news",
                            "content": json.dumps({"status": "ok", "articles": []}),
                        }
                    ]
                },
            }
        ]

        media = _extract_media_from_events(events)
        self.assertEqual(len(media), 0)

    def test_skips_failed_tool_results(self) -> None:
        from analyst.runtime.chat import _extract_media_from_events

        events = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_name": "analyst__generate_image",
                            "content": json.dumps({"status": "error", "error": "API failure"}),
                        }
                    ]
                },
            }
        ]

        media = _extract_media_from_events(events)
        self.assertEqual(len(media), 0)

    def test_returns_empty_for_no_events(self) -> None:
        from analyst.runtime.chat import _extract_media_from_events

        self.assertEqual(_extract_media_from_events([]), [])


class EngineContextInjectionTest(unittest.TestCase):
    """Tests for engine context pre-computation and injection."""

    def test_build_engine_context_produces_markdown(self) -> None:
        from analyst.runtime.chat import _build_engine_context

        engine = MagicMock()
        engine.get_regime_summary.return_value = MagicMock(body_markdown="VIX elevated, risk-off regime.")
        engine.get_calendar.return_value = [
            MagicMock(indicator="CPI", country="US", expected="3.1%", previous="3.0%", notes="Core"),
        ]
        engine.build_premarket_briefing.return_value = MagicMock(body_markdown="Futures down on tariff news.")

        context = _build_engine_context(engine)

        self.assertIn("Macro Regime", context)
        self.assertIn("VIX elevated", context)
        self.assertIn("Upcoming Calendar", context)
        self.assertIn("CPI", context)
        self.assertIn("Pre-Market Briefing", context)
        self.assertIn("tariff", context)

    def test_build_engine_context_handles_empty_data(self) -> None:
        from analyst.runtime.chat import _build_engine_context

        engine = MagicMock()
        engine.get_regime_summary.return_value = MagicMock(body_markdown="")
        engine.get_calendar.return_value = []
        engine.build_premarket_briefing.return_value = MagicMock(body_markdown="")

        context = _build_engine_context(engine)
        self.assertEqual(context, "")

    def test_build_engine_context_handles_exceptions(self) -> None:
        from analyst.runtime.chat import _build_engine_context

        engine = MagicMock()
        engine.get_regime_summary.side_effect = RuntimeError("unavailable")
        engine.get_calendar.side_effect = RuntimeError("unavailable")
        engine.build_premarket_briefing.side_effect = RuntimeError("unavailable")

        context = _build_engine_context(engine)
        self.assertEqual(context, "")


class ExecutorAlwaysNativeTest(unittest.TestCase):
    """Tests for ClaudeCodeExecutor always-native execution path."""

    def test_executor_always_uses_native_mode(self) -> None:
        from analyst.engine.executor import ClaudeCodeExecutor, AgentRunRequest
        from analyst.engine.live_types import AgentTool

        stream_stdout = "\n".join([
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "hello"}]}}),
            json.dumps({"type": "result", "is_error": False, "result": "hello"}),
        ])
        completed = MagicMock(returncode=0, stdout=stream_stdout, stderr="")
        runner = MagicMock(return_value=completed)
        provider = ClaudeCodeProvider(
            ClaudeCodeConfig(oauth_token="token", model="sonnet"),
            runner=runner,
        )
        executor = ClaudeCodeExecutor(provider=provider)

        tool = AgentTool(
            name="test_tool",
            description="test",
            parameters={"type": "object", "properties": {}},
            handler=lambda _: {},
        )
        result = executor.run_turn(AgentRunRequest(
            system_prompt="system",
            user_prompt="hi",
            tools=[tool],
        ))

        self.assertEqual(result.final_text, "hello")
        command = runner.call_args.args[0]
        self.assertIn("--input-format", command)
        self.assertIn("stream-json", command)

    def test_resolve_plan_always_native_for_claude_code(self) -> None:
        from analyst.engine.executor import ClaudeCodeExecutor
        from analyst.runtime.chat import resolve_turn_execution_plan

        completed = MagicMock(returncode=0, stdout="", stderr="")
        runner = MagicMock(return_value=completed)
        provider = ClaudeCodeProvider(
            ClaudeCodeConfig(oauth_token="token", model="sonnet"),
            runner=runner,
        )
        executor = ClaudeCodeExecutor(provider=provider)

        plan = resolve_turn_execution_plan(
            executor=executor,
            tools=[MagicMock(name="test")],
            user_text="selfie please",
            user_content=None,
        )

        self.assertTrue(plan.use_native_execution)
        self.assertEqual(plan.active_tools, [])
        self.assertIn("WebSearch", plan.native_tool_names)


if __name__ == "__main__":
    unittest.main()
