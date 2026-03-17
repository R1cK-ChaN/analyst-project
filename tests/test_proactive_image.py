"""Tests for proactive outreach image support (Phase 2).

Covers: proactive reply with/without tools, frequency caps, image hint generation.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst.delivery.image_decision import (
    should_generate_image,
)
from analyst.runtime.chat import (
    _proactive_image_hint,
    _proactive_companion_instruction,
    generate_proactive_companion_reply,
)


# ---------------------------------------------------------------------------
# Proactive image hint tests
# ---------------------------------------------------------------------------

class TestProactiveImageHint(unittest.TestCase):
    def test_warm_up_share_hint(self):
        hint = _proactive_image_hint("warm_up_share")
        self.assertIn("back_camera", hint)

    def test_streak_save_hint(self):
        hint = _proactive_image_hint("streak_save")
        self.assertIn("照片", hint)

    def test_stage_milestone_hint(self):
        hint = _proactive_image_hint("stage_milestone")
        self.assertIn("selfie", hint)

    def test_morning_hint(self):
        hint = _proactive_image_hint("morning")
        self.assertIn("场景", hint)

    def test_evening_hint(self):
        hint = _proactive_image_hint("evening")
        self.assertIn("场景", hint)

    def test_weekend_hint(self):
        hint = _proactive_image_hint("weekend")
        self.assertIn("场景", hint)

    def test_unknown_kind_empty(self):
        hint = _proactive_image_hint("inactivity")
        self.assertEqual(hint, "")

    def test_follow_up_empty(self):
        hint = _proactive_image_hint("follow_up")
        self.assertEqual(hint, "")


# ---------------------------------------------------------------------------
# Proactive decision with frequency caps
# ---------------------------------------------------------------------------

class TestProactiveDecisionCaps(unittest.TestCase):
    def test_proactive_allowed_when_no_images_today(self):
        decision = should_generate_image(
            reply_text="", relationship_stage="familiar",
            images_sent_today=0, turns_since_last_image=999,
            current_hour=14, is_proactive=True, outreach_kind="warm_up_share",
            user_text="", proactive_images_today=0, warmup_images_last_5_days=0,
        )
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.recommended)

    def test_proactive_blocked_after_1_per_day(self):
        decision = should_generate_image(
            reply_text="", relationship_stage="familiar",
            images_sent_today=0, turns_since_last_image=999,
            current_hour=14, is_proactive=True, outreach_kind="morning",
            user_text="", proactive_images_today=1,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.block_reason, "proactive_daily_limit")

    def test_warmup_blocked_after_1_per_5_days(self):
        decision = should_generate_image(
            reply_text="", relationship_stage="familiar",
            images_sent_today=0, turns_since_last_image=999,
            current_hour=14, is_proactive=True, outreach_kind="warm_up_share",
            user_text="", proactive_images_today=0, warmup_images_last_5_days=1,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.block_reason, "warmup_5day_limit")


# ---------------------------------------------------------------------------
# Proactive reply generation with tools
# ---------------------------------------------------------------------------

class TestProactiveReplyWithTools(unittest.TestCase):
    def test_without_tools_returns_empty_media(self):
        mock_executor = MagicMock()
        mock_result = MagicMock()
        mock_result.final_text = "早安！今天天气不错。"
        mock_result.messages = []
        mock_result.raw_response = {}
        mock_executor.run_turn.return_value = mock_result
        mock_executor.backend = MagicMock()
        mock_executor.backend.value = "openrouter"
        mock_executor.mcp_tool_names = ()

        with patch("analyst.runtime.chat.coerce_agent_executor", return_value=mock_executor):
            reply = generate_proactive_companion_reply(
                kind="morning",
                agent_loop=mock_executor,
                tools=None,
                memory_context="",
                preferred_language="zh",
            )
        self.assertEqual(reply.media, [])
        self.assertEqual(reply.tool_audit, [])

    def test_with_tools_passes_tools_to_executor(self):
        mock_executor = MagicMock()
        mock_result = MagicMock()
        mock_result.final_text = "看到一只猫！"
        mock_result.messages = []
        mock_result.raw_response = {}
        mock_executor.run_turn.return_value = mock_result
        mock_executor.backend = MagicMock()
        mock_executor.backend.value = "openrouter"
        mock_executor.mcp_tool_names = ()

        mock_tool = MagicMock()
        mock_tool.name = "generate_image"

        with patch("analyst.runtime.chat.coerce_agent_executor", return_value=mock_executor):
            reply = generate_proactive_companion_reply(
                kind="warm_up_share",
                agent_loop=mock_executor,
                tools=[mock_tool],
                memory_context="",
                preferred_language="zh",
            )
        # Verify tools were passed to run_turn
        call_args = mock_executor.run_turn.call_args
        request = call_args[0][0]
        self.assertEqual(len(request.tools), 1)
        self.assertEqual(request.tools[0].name, "generate_image")

    def test_instruction_includes_image_hint_when_tools_provided(self):
        mock_executor = MagicMock()
        mock_result = MagicMock()
        mock_result.final_text = "分享一个有趣的东西"
        mock_result.messages = []
        mock_result.raw_response = {}
        mock_executor.run_turn.return_value = mock_result
        mock_executor.backend = MagicMock()
        mock_executor.backend.value = "openrouter"
        mock_executor.mcp_tool_names = ()

        mock_tool = MagicMock()
        mock_tool.name = "generate_image"

        with patch("analyst.runtime.chat.coerce_agent_executor", return_value=mock_executor):
            generate_proactive_companion_reply(
                kind="warm_up_share",
                agent_loop=mock_executor,
                tools=[mock_tool],
                memory_context="",
                preferred_language="zh",
            )
        call_args = mock_executor.run_turn.call_args
        request = call_args[0][0]
        self.assertIn("back_camera", request.user_prompt)


# ---------------------------------------------------------------------------
# Instruction text tests
# ---------------------------------------------------------------------------

class TestProactiveInstructionContent(unittest.TestCase):
    def test_warm_up_share_instruction_unchanged(self):
        instruction = _proactive_companion_instruction("warm_up_share")
        self.assertIn("触达类型", instruction)
        self.assertIn("随手分享", instruction)

    def test_morning_instruction_unchanged(self):
        instruction = _proactive_companion_instruction("morning")
        self.assertIn("morning", instruction.lower())


if __name__ == "__main__":
    unittest.main()
