"""Tests for the Telegram delivery layer.

Covers:
- TelegramFormatter produces correct ChannelMessage fields
- Truncation for oversized messages
- Integration routing via handle_message (channel-agnostic)
- Bot handler wiring (build_application returns correct handlers)
- Agent-loop chat reply flow (persona, history, tools, truncation, errors)
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst import build_demo_app
from analyst.contracts import (
    DraftResponse,
    InteractionMode,
    ResearchNote,
    RegimeScore,
    RegimeState,
    SourceReference,
    utc_now,
)
from analyst.delivery.telegram import MAX_TELEGRAM_MESSAGE_LENGTH, TelegramFormatter, _truncate_body
from analyst.engine import AnalystEngine
from analyst.engine.live_types import AgentLoopResult, ConversationMessage
from analyst.information import AnalystInformationService, FileBackedInformationRepository
from analyst.integration import AnalystIntegrationService, detect_mode
from analyst.runtime import TemplateAgentRuntime


class TestTruncateBody(unittest.TestCase):
    def test_short_body_unchanged(self) -> None:
        result = _truncate_body("hello", "\nfooter")
        self.assertEqual(result, "hello\nfooter")

    def test_body_plus_suffix_at_limit(self) -> None:
        suffix = "\nfooter"
        body = "a" * (MAX_TELEGRAM_MESSAGE_LENGTH - len(suffix))
        result = _truncate_body(body, suffix)
        self.assertEqual(len(result), MAX_TELEGRAM_MESSAGE_LENGTH)
        self.assertTrue(result.endswith(suffix))

    def test_long_body_truncated_but_suffix_preserved(self) -> None:
        suffix = "\n\n合规提示: disclaimer"
        body = "a" * (MAX_TELEGRAM_MESSAGE_LENGTH + 500)
        result = _truncate_body(body, suffix)
        self.assertLessEqual(len(result), MAX_TELEGRAM_MESSAGE_LENGTH)
        self.assertTrue(result.endswith(suffix))
        self.assertIn("\n...", result)


class TestTelegramFormatter(unittest.TestCase):
    def setUp(self) -> None:
        self.formatter = TelegramFormatter()

    def _make_draft_response(self, mode: InteractionMode = InteractionMode.QA) -> DraftResponse:
        return DraftResponse(
            request_id="test-001",
            created_at=utc_now(),
            mode=mode,
            audience="internal_rm",
            markdown="### Test\nSome content",
            plain_text="Test\nSome content",
            citations=[],
            metadata={"focus": "global"},
        )

    def _make_research_note(self) -> ResearchNote:
        regime = RegimeState(
            as_of=utc_now(),
            summary="Test summary",
            scores=[
                RegimeScore(axis="risk_sentiment", score=50.0, label="neutral", rationale="test"),
            ],
            evidence=[],
            confidence=0.7,
        )
        return ResearchNote(
            note_id="note-001",
            created_at=utc_now(),
            note_type="regime_summary",
            title="Test Note",
            summary="Test summary",
            body_markdown="### Body\nContent here",
            regime_state=regime,
            citations=[],
            tags=["test"],
        )

    def test_format_draft_channel_is_telegram(self) -> None:
        msg = self.formatter.format_draft(self._make_draft_response())
        self.assertEqual(msg.channel, "telegram")

    def test_format_draft_includes_compliance(self) -> None:
        msg = self.formatter.format_draft(self._make_draft_response())
        self.assertIn("合规提示", msg.markdown)
        self.assertIn("合规提示", msg.plain_text)

    def test_format_draft_preserves_mode(self) -> None:
        for mode in [InteractionMode.QA, InteractionMode.DRAFT, InteractionMode.MEETING_PREP]:
            msg = self.formatter.format_draft(self._make_draft_response(mode=mode))
            self.assertEqual(msg.mode, mode)

    def test_format_draft_preserves_message_id(self) -> None:
        msg = self.formatter.format_draft(self._make_draft_response())
        self.assertEqual(msg.message_id, "test-001")

    def test_format_research_note_channel_is_telegram(self) -> None:
        msg = self.formatter.format_research_note(self._make_research_note())
        self.assertEqual(msg.channel, "telegram")

    def test_format_research_note_includes_title(self) -> None:
        msg = self.formatter.format_research_note(self._make_research_note())
        self.assertIn("Test Note", msg.markdown)

    def test_format_research_note_includes_compliance(self) -> None:
        msg = self.formatter.format_research_note(self._make_research_note())
        self.assertIn("合规提示", msg.markdown)

    def test_format_calendar_channel_is_telegram(self) -> None:
        app = build_demo_app()
        items = app.engine.get_calendar(limit=2)
        msg = self.formatter.format_calendar(items)
        self.assertEqual(msg.channel, "telegram")
        self.assertEqual(msg.mode, InteractionMode.CALENDAR)
        self.assertIn("合规提示", msg.markdown)

    def test_format_calendar_metadata_has_count(self) -> None:
        app = build_demo_app()
        items = app.engine.get_calendar(limit=3)
        msg = self.formatter.format_calendar(items)
        self.assertEqual(msg.metadata["items"], str(len(items)))

    def test_format_calendar_plain_text_includes_compliance(self) -> None:
        """Finding 3: calendar plain_text must include the disclaimer."""
        app = build_demo_app()
        items = app.engine.get_calendar(limit=2)
        msg = self.formatter.format_calendar(items)
        self.assertIn("合规提示", msg.plain_text)

    def test_format_research_note_plain_text_includes_body(self) -> None:
        """Finding 2: plain_text must include the full body, not just summary."""
        note = self._make_research_note()
        msg = self.formatter.format_research_note(note)
        self.assertIn("Content here", msg.plain_text)

    def test_format_draft_disclaimer_survives_truncation(self) -> None:
        """Finding 1: compliance disclaimer must survive even on oversized messages."""
        long_response = DraftResponse(
            request_id="long-001",
            created_at=utc_now(),
            mode=InteractionMode.DRAFT,
            audience="client_draft",
            markdown="x" * 5000,
            plain_text="x" * 5000,
            citations=[],
            metadata={},
        )
        msg = self.formatter.format_draft(long_response)
        self.assertLessEqual(len(msg.plain_text), MAX_TELEGRAM_MESSAGE_LENGTH)
        self.assertIn("合规提示", msg.plain_text)
        self.assertLessEqual(len(msg.markdown), MAX_TELEGRAM_MESSAGE_LENGTH)
        self.assertIn("合规提示", msg.markdown)


class TestIntegrationWithTelegramFormatter(unittest.TestCase):
    """Verify that AnalystIntegrationService works with TelegramFormatter."""

    def setUp(self) -> None:
        repository = FileBackedInformationRepository()
        info_service = AnalystInformationService(repository)
        runtime = TemplateAgentRuntime()
        engine = AnalystEngine(info_service=info_service, runtime=runtime)
        formatter = TelegramFormatter()
        self.integration = AnalystIntegrationService(engine=engine, formatter=formatter)

    def test_handle_message_draft_route(self) -> None:
        reply = self.integration.handle_message(
            "帮我写一段关于今晚非农数据的客户消息", user_id="tg-001"
        )
        self.assertEqual(reply.channel, "telegram")
        self.assertEqual(reply.mode, InteractionMode.DRAFT)
        self.assertIn("客户消息初稿", reply.markdown)
        self.assertIn("合规提示", reply.markdown)

    def test_handle_message_regime_route(self) -> None:
        reply = self.integration.handle_message("现在宏观整体怎么看？", user_id="tg-002")
        self.assertEqual(reply.channel, "telegram")
        self.assertEqual(reply.mode, InteractionMode.REGIME)
        self.assertIn("合规提示", reply.markdown)

    def test_handle_message_calendar_route(self) -> None:
        reply = self.integration.handle_message("今天有什么数据？", user_id="tg-003")
        self.assertEqual(reply.channel, "telegram")
        self.assertEqual(reply.mode, InteractionMode.CALENDAR)

    def test_handle_message_qa_fallback(self) -> None:
        reply = self.integration.handle_message("美联储下次什么时候开会？", user_id="tg-004")
        self.assertEqual(reply.channel, "telegram")
        self.assertEqual(reply.mode, InteractionMode.QA)

    def test_handle_wecom_message_still_works(self) -> None:
        """Backward compatibility: handle_wecom_message delegates to handle_message."""
        reply = self.integration.handle_wecom_message("帮我写一段客户消息", user_id="rm-001")
        self.assertEqual(reply.channel, "telegram")
        self.assertEqual(reply.mode, InteractionMode.DRAFT)


class TestBuildApplication(unittest.TestCase):
    """Verify bot wiring without actually starting polling."""

    def test_build_application_registers_handlers(self) -> None:
        try:
            from analyst.delivery.bot import build_application
            from analyst.engine.live_provider import OpenRouterConfig
        except ImportError:
            self.skipTest("python-telegram-bot not installed")

        with patch(
            "analyst.delivery.bot.OpenRouterConfig.from_env",
            return_value=OpenRouterConfig(
                api_key="test-key",
                model="google/gemini-3.1-flash-lite-preview",
            ),
        ):
            app = build_application("fake-token-for-test")
        handlers = app.handlers.get(0, [])
        # 5 command handlers + 1 message handler = 6
        self.assertEqual(len(handlers), 6)


class TestChatReply(unittest.IsolatedAsyncioTestCase):
    """Test _chat_reply — the core agent-loop chat function."""

    def setUp(self) -> None:
        self.mock_loop = MagicMock()
        self.mock_tools = []
        self.mock_context = MagicMock()
        self.mock_context.user_data = {}

    def _set_loop_response(self, text: str) -> None:
        self.mock_loop.run.return_value = AgentLoopResult(
            messages=[
                ConversationMessage(role="user", content="test"),
                ConversationMessage(role="assistant", content=text),
            ],
            final_text=text,
            events=[],
        )

    async def test_calls_agent_loop_with_soul_prompt(self) -> None:
        from analyst.delivery.bot import _chat_reply
        from analyst.delivery.soul import SOUL_SYSTEM_PROMPT

        self._set_loop_response("你好！")
        await _chat_reply("hi", self.mock_context, self.mock_loop, self.mock_tools)

        call_kwargs = self.mock_loop.run.call_args.kwargs
        self.assertEqual(call_kwargs["system_prompt"], SOUL_SYSTEM_PROMPT)
        self.assertIn("陈襄", call_kwargs["system_prompt"])

    async def test_passes_tools_to_agent_loop(self) -> None:
        from analyst.delivery.bot import _chat_reply

        fake_tools = [MagicMock(), MagicMock()]
        self._set_loop_response("ok")
        await _chat_reply("hi", self.mock_context, self.mock_loop, fake_tools)

        call_kwargs = self.mock_loop.run.call_args.kwargs
        self.assertIs(call_kwargs["tools"], fake_tools)

    async def test_includes_conversation_history(self) -> None:
        from analyst.delivery.bot import _chat_reply

        self.mock_context.user_data["history"] = [
            {"role": "user", "content": "first message"},
            {"role": "assistant", "content": "first reply"},
        ]
        self._set_loop_response("second reply")
        await _chat_reply("second message", self.mock_context, self.mock_loop, self.mock_tools)

        call_kwargs = self.mock_loop.run.call_args.kwargs
        history = call_kwargs["history"]
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].content, "first message")
        self.assertEqual(history[1].content, "first reply")
        self.assertEqual(call_kwargs["user_prompt"], "second message")

    async def test_appends_to_history(self) -> None:
        from analyst.delivery.bot import _chat_reply

        self._set_loop_response("hello back")
        await _chat_reply("hello", self.mock_context, self.mock_loop, self.mock_tools)

        history = self.mock_context.user_data["history"]
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0], {"role": "user", "content": "hello"})
        self.assertEqual(history[1], {"role": "assistant", "content": "hello back"})

    async def test_truncates_long_response(self) -> None:
        from analyst.delivery.bot import MAX_TELEGRAM_LENGTH, _chat_reply

        self._set_loop_response("x" * 5000)
        result = await _chat_reply("hi", self.mock_context, self.mock_loop, self.mock_tools)

        self.assertLessEqual(len(result), MAX_TELEGRAM_LENGTH)
        self.assertTrue(result.endswith("..."))

    async def test_history_trimming(self) -> None:
        from analyst.delivery.bot import MAX_HISTORY_TURNS, _chat_reply

        self.mock_context.user_data["history"] = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg-{i}"}
            for i in range(MAX_HISTORY_TURNS * 2 + 10)
        ]
        self._set_loop_response("ok")
        await _chat_reply("new msg", self.mock_context, self.mock_loop, self.mock_tools)

        history = self.mock_context.user_data["history"]
        self.assertLessEqual(len(history), MAX_HISTORY_TURNS * 2)

    async def test_agent_loop_error_fallback(self) -> None:
        from analyst.delivery.bot import _chat_reply

        self.mock_loop.run.side_effect = RuntimeError("API down")
        result = await _chat_reply("hello", self.mock_context, self.mock_loop, self.mock_tools)

        self.assertIn("抱歉", result)
        history = self.mock_context.user_data["history"]
        self.assertEqual(len(history), 2)


if __name__ == "__main__":
    unittest.main()
