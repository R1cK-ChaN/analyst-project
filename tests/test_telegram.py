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
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
from analyst.engine.live_types import AgentLoopResult, AgentTool, ConversationMessage
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
        self.assertEqual(len(handlers), 5)
        command_names = [handler.commands for handler in handlers if hasattr(handler, "commands")]
        self.assertEqual(
            command_names,
            [{"start"}, {"help"}, {"checkins_on"}, {"checkins_off"}],
        )


class TestChatPersonaRouting(unittest.TestCase):
    def test_companion_tools_exclude_finance_and_web_tools(self) -> None:
        from analyst.delivery.sales_chat import ChatPersonaMode, build_chat_tools, build_companion_services, COMPANION_DEFAULT_MODEL

        image_tool = AgentTool(name="generate_image", description="", parameters={}, handler=lambda _: {})
        live_tool = AgentTool(name="generate_live_photo", description="", parameters={}, handler=lambda _: {})

        with patch("analyst.delivery.sales_chat.build_image_gen_tool", return_value=image_tool), \
             patch("analyst.delivery.sales_chat.build_optional_live_photo_tool", return_value=live_tool):
            tools = build_chat_tools(
                engine=MagicMock(),
                store=MagicMock(),
                provider=MagicMock(),
                persona_mode=ChatPersonaMode.COMPANION,
            )

        self.assertEqual([tool.name for tool in tools], ["generate_image", "generate_live_photo"])

    def test_companion_services_use_companion_default_model(self) -> None:
        from analyst.delivery.sales_chat import (
            COMPANION_DEFAULT_MODEL,
            OpenRouterConfig,
            build_companion_services,
        )

        with patch(
            "analyst.delivery.sales_chat.OpenRouterConfig.from_env",
            return_value=OpenRouterConfig(api_key="test-key", model=COMPANION_DEFAULT_MODEL),
        ) as config_mock, \
             patch("analyst.delivery.sales_chat.build_image_gen_tool", return_value=MagicMock()), \
             patch("analyst.delivery.sales_chat.build_optional_live_photo_tool", return_value=MagicMock()):
            build_companion_services()

        kwargs = config_mock.call_args.kwargs
        self.assertEqual(kwargs["default_model"], COMPANION_DEFAULT_MODEL)
        self.assertIn("ANALYST_COMPANION_OPENROUTER_MODEL", kwargs["model_keys"])


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

    async def test_calls_agent_loop_with_companion_prompt_by_default(self) -> None:
        from analyst.delivery.bot import _chat_reply
        from analyst.delivery.soul import COMPANION_SYSTEM_PROMPT

        self._set_loop_response("你好！")
        await _chat_reply("hi", self.mock_context, self.mock_loop, self.mock_tools)

        call_kwargs = self.mock_loop.run.call_args.kwargs
        self.assertIn(COMPANION_SYSTEM_PROMPT, call_kwargs["system_prompt"])
        self.assertIn("陈襄", call_kwargs["system_prompt"])

    async def test_companion_prompt_includes_latent_snt_backstory(self) -> None:
        from analyst.delivery.bot import _chat_reply
        from analyst.delivery.sales_chat import ChatPersonaMode
        from analyst.delivery.soul import COMPANION_SYSTEM_PROMPT

        self._set_loop_response("晚上好")
        await _chat_reply(
            "hi",
            self.mock_context,
            self.mock_loop,
            self.mock_tools,
            persona_mode=ChatPersonaMode.COMPANION,
        )

        call_kwargs = self.mock_loop.run.call_args.kwargs
        self.assertIn(COMPANION_SYSTEM_PROMPT, call_kwargs["system_prompt"])
        self.assertIn("SnT team", call_kwargs["system_prompt"])
        self.assertIn("不要主动聊金融", call_kwargs["system_prompt"])
        self.assertNotIn("投研老兵", call_kwargs["system_prompt"])

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

        self.assertLessEqual(len(result.text), MAX_TELEGRAM_LENGTH)
        self.assertTrue(result.text.endswith("..."))

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

        self.assertIn("抱歉", result.text)
        history = self.mock_context.user_data["history"]
        self.assertEqual(len(history), 2)

    async def test_strips_profile_update_and_markdown_from_public_reply(self) -> None:
        from analyst.delivery.bot import _chat_reply

        self._set_loop_response(
            "### 直接回答\n- 我偏谨慎。\n<profile_update>{\"current_mood\":\"谨慎\",\"confidence\":\"中\"}</profile_update>"
        )
        result = await _chat_reply("hello", self.mock_context, self.mock_loop, self.mock_tools)

        self.assertEqual(result.text, "直接回答\n我偏谨慎。")
        self.assertEqual(result.profile_update.current_mood, "cautious")
        self.assertEqual(result.profile_update.confidence, "medium")

    async def test_repairs_literal_image_placeholder_with_generate_image_tool(self) -> None:
        from analyst.delivery.bot import _chat_reply

        self._set_loop_response(
            "行啊，稍等我一下。[SPLIT]这就发你。 [IMAGE]<profile_update>{}</profile_update>"
        )
        image_tool = AgentTool(
            name="generate_image",
            description="",
            parameters={},
            handler=lambda arguments: {
                "status": "ok",
                "image_url": "https://example.com/selfie.jpg",
                "mode": "selfie",
            },
        )

        result = await _chat_reply("看看自拍 静态就行", self.mock_context, self.mock_loop, [image_tool])

        self.assertEqual(result.text, "行啊，稍等我一下。[SPLIT]这就发你。")
        self.assertEqual(len(result.media), 1)
        self.assertEqual(result.media[0].kind, "photo")
        self.assertEqual(result.media[0].url, "https://example.com/selfie.jpg")
        self.assertEqual(len(result.tool_audit), 1)
        self.assertEqual(result.tool_audit[0]["tool_name"], "generate_image")
        self.assertEqual(result.tool_audit[0]["status"], "ok")
        self.assertEqual(result.tool_audit[0]["repair_kind"], "placeholder_image")
        self.assertEqual(result.tool_audit[0]["arguments"]["mode"], "selfie")


class TestGroupChat(unittest.IsolatedAsyncioTestCase):
    """Tests for group chat support — silent observation, mention-triggered replies."""

    def setUp(self) -> None:
        self.mock_loop = MagicMock()
        self.mock_tools = []
        self.mock_store = MagicMock()

        async def run_inline(func, /, *args, **kwargs):
            return func(*args, **kwargs)

        self.to_thread_patcher = patch(
            "analyst.delivery.bot.asyncio.to_thread",
            new=AsyncMock(side_effect=run_inline),
        )
        self.to_thread_patcher.start()
        self.addCleanup(self.to_thread_patcher.stop)

        self.mock_store.get_client_profile.return_value = SimpleNamespace(
            preferred_language="zh",
            response_style="",
            current_mood="",
            emotional_trend="",
            stress_level="",
            confidence="",
            notes="",
            personal_facts=[],
            total_interactions=0,
            last_active_at="",
        )
        self.mock_store.list_group_messages.return_value = []
        self.mock_store.list_group_members.return_value = []
        self.mock_store.build_sales_context = MagicMock(return_value="")

        self.mock_loop.run.return_value = AgentLoopResult(
            messages=[
                ConversationMessage(role="user", content="test"),
                ConversationMessage(role="assistant", content="reply text"),
            ],
            final_text="reply text",
            events=[],
        )

    def _make_update(
        self,
        text: str = "hello",
        caption: str | None = None,
        chat_type: str = "supergroup",
        chat_id: int = -100123,
        user_id: int = 42,
        first_name: str = "Alice",
        entities: dict | None = None,
        caption_entities: dict | None = None,
        reply_to_bot: bool = False,
        bot_id: int = 999,
        with_photo: bool = False,
        document_mime_type: str | None = None,
    ) -> tuple:
        """Build mock Update + Context for group/private scenarios."""
        update = MagicMock()
        update.effective_chat.type = chat_type
        update.effective_chat.id = chat_id
        update.effective_chat.send_action = AsyncMock()
        update.effective_message.text = text
        update.effective_message.caption = caption
        update.effective_message.message_thread_id = None
        update.effective_message.reply_text = AsyncMock()
        update.effective_message.reply_photo = AsyncMock()
        update.effective_message.reply_video = AsyncMock()
        update.effective_user.id = user_id
        update.effective_user.first_name = first_name
        update.effective_message.photo = []
        update.effective_message.document = None

        if entities is None:
            update.effective_message.parse_entities.return_value = {}
        else:
            update.effective_message.parse_entities.return_value = entities
        if caption_entities is None:
            update.effective_message.parse_caption_entities.return_value = {}
        else:
            update.effective_message.parse_caption_entities.return_value = caption_entities

        if with_photo:
            photo = MagicMock()
            photo.file_id = "photo-file-id"
            update.effective_message.photo = [photo]
        if document_mime_type is not None:
            document = MagicMock()
            document.file_id = "document-file-id"
            document.file_name = "upload.png"
            document.mime_type = document_mime_type
            update.effective_message.document = document

        if reply_to_bot:
            reply_user = MagicMock()
            reply_user.id = bot_id
            update.effective_message.reply_to_message.from_user = reply_user
            update.effective_message.reply_to_message.text = None
            update.effective_message.reply_to_message.caption = None
            update.effective_message.reply_to_message.quote = None
        else:
            update.effective_message.reply_to_message = None

        context = MagicMock()
        context.bot.username = "testbot"
        context.bot.id = bot_id
        context.bot.get_file = AsyncMock()
        context.user_data = {}
        context.chat_data = {}

        return update, context

    def test_is_group_chat_detection(self) -> None:
        from analyst.delivery.bot import _is_group_chat

        for chat_type in ("group", "supergroup"):
            update, _ = self._make_update(chat_type=chat_type)
            self.assertTrue(_is_group_chat(update), f"Should detect {chat_type}")

        update, _ = self._make_update(chat_type="private")
        self.assertFalse(_is_group_chat(update))

    def test_mention_stripping(self) -> None:
        from analyst.delivery.bot import _strip_bot_mention

        self.assertEqual(_strip_bot_mention("@testbot what?", "testbot"), "what?")

    def test_mention_mid_sentence(self) -> None:
        from analyst.delivery.bot import _strip_bot_mention

        self.assertEqual(_strip_bot_mention("hey @testbot check", "testbot"), "hey  check")

    async def test_group_message_without_mention_no_reply(self) -> None:
        from analyst.delivery.bot import _make_message_handler

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        update, context = self._make_update(text="some random chat", chat_type="supergroup")
        await handler(update, context)

        # Bot should NOT have replied
        update.effective_message.reply_text.assert_not_called()
        # But the message should be in the group buffer
        self.assertIn("group_buffers", context.chat_data)
        buf = context.chat_data["group_buffers"]["main"]
        self.assertEqual(len(buf), 1)
        self.assertEqual(buf[0]["text"], "some random chat")

    async def test_group_message_with_mention_triggers_reply(self) -> None:
        from analyst.delivery.bot import _make_message_handler

        # Build a mention entity
        mention_entity = MagicMock()
        mention_entity.type = "mention"
        entities = {mention_entity: "@testbot"}

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        update, context = self._make_update(
            text="@testbot what's the regime?", chat_type="supergroup", entities=entities,
        )

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction"):
            await handler(update, context)

        update.effective_message.reply_text.assert_called()

    async def test_group_photo_caption_mention_triggers_reply(self) -> None:
        from analyst.delivery.bot import _make_message_handler

        mention_entity = MagicMock()
        mention_entity.type = "mention"
        caption_entities = {mention_entity: "@testbot"}
        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        update, context = self._make_update(
            text="",
            caption="@testbot animate this",
            chat_type="supergroup",
            caption_entities=caption_entities,
            with_photo=True,
        )
        telegram_file = MagicMock()
        telegram_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"fake image bytes"))
        context.bot.get_file.return_value = telegram_file

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction"):
            await handler(update, context)

        update.effective_message.reply_text.assert_called()

    async def test_reply_to_bot_triggers_reply(self) -> None:
        from analyst.delivery.bot import _make_message_handler

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        update, context = self._make_update(
            text="can you elaborate?", chat_type="supergroup", reply_to_bot=True,
        )

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction"):
            await handler(update, context)

        update.effective_message.reply_text.assert_called()

    async def test_group_context_accumulates(self) -> None:
        from analyst.delivery.bot import _make_message_handler

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        # Send 3 messages without mention — all should buffer, none should reply
        for i in range(3):
            update, context = self._make_update(
                text=f"message {i}", chat_type="supergroup", user_id=42 + i,
            )
            if i == 0:
                saved_context = context
            else:
                # Reuse same chat_data to simulate same chat
                context.chat_data = saved_context.chat_data
            await handler(update, context)

        buf = saved_context.chat_data["group_buffers"]["main"]
        self.assertEqual(len(buf), 3)

    async def test_group_context_rendered_in_prompt(self) -> None:
        from analyst.delivery.bot import _make_message_handler

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)

        # Pre-populate buffer with some context
        update, context = self._make_update(
            text="the market is wild today", chat_type="supergroup",
        )
        await handler(update, context)  # buffered, no reply

        # Now send a mention
        mention_entity = MagicMock()
        mention_entity.type = "mention"
        entities = {mention_entity: "@testbot"}
        update2, _ = self._make_update(
            text="@testbot what do you think?", chat_type="supergroup", entities=entities,
        )
        # Reuse chat_data
        context2 = MagicMock()
        context2.bot.username = "testbot"
        context2.bot.id = 999
        context2.user_data = {}
        context2.chat_data = context.chat_data

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction"):
            await handler(update2, context2)

        # Verify the agent loop was called with group context in system prompt
        call_kwargs = self.mock_loop.run.call_args.kwargs
        self.assertIn("GROUP CHAT MODE", call_kwargs["system_prompt"])

    async def test_private_chat_unchanged(self) -> None:
        from analyst.delivery.bot import _make_message_handler

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        update, context = self._make_update(text="hello", chat_type="private")

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction"):
            await handler(update, context)

        # Private chat always triggers a reply
        update.effective_message.reply_text.assert_called()

    async def test_private_photo_message_passes_multimodal_prompt(self) -> None:
        from analyst.delivery.bot import _make_message_handler

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        update, context = self._make_update(
            text="",
            caption="make this move",
            chat_type="private",
            with_photo=True,
        )
        telegram_file = MagicMock()
        telegram_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"fake image bytes"))
        context.bot.get_file.return_value = telegram_file

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction") as mock_record:
            await handler(update, context)

        call_kwargs = self.mock_loop.run.call_args.kwargs
        self.assertIsInstance(call_kwargs["user_prompt"], list)
        self.assertEqual(call_kwargs["user_prompt"][1]["type"], "image_url")
        self.assertTrue(
            call_kwargs["user_prompt"][1]["image_url"]["url"].startswith("data:image/")
        )
        mock_record.assert_called_once()
        self.assertIn("[Image attached]", mock_record.call_args.kwargs["user_text"])

    async def test_private_image_document_passes_multimodal_prompt(self) -> None:
        from analyst.delivery.bot import _make_message_handler

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        update, context = self._make_update(
            text="turn this into a poster",
            chat_type="private",
            document_mime_type="image/png",
        )
        telegram_file = MagicMock()
        telegram_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"fake image bytes"))
        context.bot.get_file.return_value = telegram_file

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction"):
            await handler(update, context)

        call_kwargs = self.mock_loop.run.call_args.kwargs
        self.assertIsInstance(call_kwargs["user_prompt"], list)
        self.assertEqual(call_kwargs["user_prompt"][0]["type"], "text")
        self.assertEqual(call_kwargs["user_prompt"][1]["type"], "image_url")

    async def test_private_reply_to_photo_uses_referenced_image(self) -> None:
        from analyst.delivery.bot import _make_message_handler
        from analyst.delivery.sales_chat import SalesChatReply
        from analyst.memory import ClientProfileUpdate

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        update, context = self._make_update(
            text="what's happening here?",
            chat_type="private",
            reply_to_bot=True,
        )
        reply_photo = MagicMock()
        reply_photo.file_id = "reply-photo-file-id"
        update.effective_message.reply_to_message.photo = [reply_photo]
        update.effective_message.reply_to_message.text = None
        update.effective_message.reply_to_message.caption = None
        telegram_file = MagicMock()
        telegram_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"fake image bytes"))
        context.bot.get_file.return_value = telegram_file

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction") as mock_record, \
             patch(
                 "analyst.delivery.bot._chat_reply",
                 new=AsyncMock(
                     return_value=SalesChatReply(
                         text="reply text",
                         profile_update=ClientProfileUpdate(),
                     )
                 ),
             ) as mock_chat_reply:
            await handler(update, context)

        call_kwargs = mock_chat_reply.call_args.kwargs
        self.assertEqual(call_kwargs["attached_image"].source, "reply")
        self.assertEqual(call_kwargs["user_content"][1]["type"], "image_url")
        self.assertIn("referenced in the replied-to message", call_kwargs["user_content"][0]["text"])
        self.assertIn("[Referenced image]", mock_record.call_args.kwargs["user_text"])

    async def test_group_reply_to_photo_with_mention_uses_referenced_image(self) -> None:
        from analyst.delivery.bot import _make_message_handler
        from analyst.delivery.sales_chat import SalesChatReply
        from analyst.memory import ClientProfileUpdate

        mention_entity = MagicMock()
        mention_entity.type = "mention"
        entities = {mention_entity: "@testbot"}
        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        update, context = self._make_update(
            text="@testbot what do you think of this?",
            chat_type="supergroup",
            entities=entities,
        )
        update.effective_message.reply_to_message = MagicMock()
        reply_user = MagicMock()
        reply_user.id = 12345
        update.effective_message.reply_to_message.from_user = reply_user
        reply_photo = MagicMock()
        reply_photo.file_id = "group-reply-photo-file-id"
        update.effective_message.reply_to_message.photo = [reply_photo]
        update.effective_message.reply_to_message.text = None
        update.effective_message.reply_to_message.caption = None
        update.effective_message.reply_to_message.quote = None
        telegram_file = MagicMock()
        telegram_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"fake image bytes"))
        context.bot.get_file.return_value = telegram_file

        with patch("analyst.delivery.bot.build_group_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction") as mock_record, \
             patch(
                 "analyst.delivery.bot._chat_reply",
                 new=AsyncMock(
                     return_value=SalesChatReply(
                         text="reply text",
                         profile_update=ClientProfileUpdate(),
                     )
                 ),
             ) as mock_chat_reply:
            await handler(update, context)

        call_kwargs = mock_chat_reply.call_args.kwargs
        self.assertEqual(call_kwargs["attached_image"].source, "reply")
        self.assertEqual(call_kwargs["user_content"][1]["type"], "image_url")
        self.assertIn("referenced in the replied-to message", call_kwargs["user_content"][0]["text"])
        self.assertIn("[Referenced image]", mock_record.call_args.kwargs["user_text"])

    async def test_private_chat_sends_and_cleans_up_generated_photo(self) -> None:
        from analyst.delivery.bot import _make_message_handler
        from analyst.delivery.sales_chat import MediaItem, SalesChatReply
        from analyst.memory import ClientProfileUpdate

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        update, context = self._make_update(text="hello", chat_type="private")
        update.effective_message.reply_photo = AsyncMock()

        with tempfile.NamedTemporaryFile(prefix="analyst_gen_", suffix=".png", delete=False) as tmp:
            tmp.write(b"fake image bytes")
            temp_path = tmp.name

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction"), \
             patch(
                 "analyst.delivery.bot._chat_reply",
                 new=AsyncMock(
                     return_value=SalesChatReply(
                         text="图片来了",
                         profile_update=ClientProfileUpdate(),
                         media=[MediaItem(kind="photo", url=temp_path)],
                     )
                 ),
             ):
            await handler(update, context)

        update.effective_message.reply_photo.assert_called_once()
        self.assertFalse(Path(temp_path).exists())

    async def test_private_chat_sends_and_cleans_up_generated_video(self) -> None:
        from analyst.delivery.bot import _make_message_handler
        from analyst.delivery.sales_chat import MediaItem, SalesChatReply
        from analyst.memory import ClientProfileUpdate

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        update, context = self._make_update(text="hello", chat_type="private")
        update.effective_message.reply_video = AsyncMock()

        with tempfile.NamedTemporaryFile(prefix="analyst_live_video_", suffix=".mp4", delete=False) as video_tmp:
            video_tmp.write(b"fake video bytes")
            video_path = video_tmp.name
        with tempfile.NamedTemporaryFile(prefix="analyst_live_photo_", suffix=".jpg", delete=False) as cover_tmp:
            cover_tmp.write(b"fake cover bytes")
            cover_path = cover_tmp.name

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction"), \
             patch(
                 "analyst.delivery.bot._chat_reply",
                 new=AsyncMock(
                     return_value=SalesChatReply(
                         text="动态自拍来了",
                         profile_update=ClientProfileUpdate(),
                         media=[
                             MediaItem(
                                 kind="video",
                                 url=video_path,
                                 cleanup_paths=(cover_path,),
                             )
                         ],
                     )
                 ),
             ):
            await handler(update, context)

        update.effective_message.reply_video.assert_called_once()
        self.assertFalse(Path(video_path).exists())
        self.assertFalse(Path(cover_path).exists())

    async def test_start_command_skipped_in_group(self) -> None:
        from analyst.delivery.bot import _make_start_handler

        handler = _make_start_handler(self.mock_loop, self.mock_tools)
        update, context = self._make_update(chat_type="supergroup")

        await handler(update, context)

        # Should not reply in group
        update.effective_message.reply_text.assert_not_called()
        update.effective_chat.send_action.assert_not_called()

    def test_extract_reply_context_no_reply(self) -> None:
        from analyst.delivery.bot import _extract_reply_context

        update, _ = self._make_update(text="hello")
        # reply_to_message is None
        self.assertIsNone(_extract_reply_context(update))

    def test_extract_reply_context_with_text(self) -> None:
        from analyst.delivery.bot import _extract_reply_context

        update, _ = self._make_update(text="what do you mean?", reply_to_bot=True)
        update.effective_message.reply_to_message.text = "the market is up 3%"
        # No quote attribute
        update.effective_message.reply_to_message.quote = None
        result = _extract_reply_context(update)
        self.assertEqual(result, "the market is up 3%")

    def test_extract_reply_context_non_text_message(self) -> None:
        from analyst.delivery.bot import _extract_reply_context

        update, _ = self._make_update(text="nice pic", reply_to_bot=True)
        update.effective_message.reply_to_message.text = None
        update.effective_message.reply_to_message.quote = None
        self.assertIsNone(_extract_reply_context(update))

    def test_extract_reply_context_prefers_quote(self) -> None:
        from analyst.delivery.bot import _extract_reply_context

        update, _ = self._make_update(text="explain this part", reply_to_bot=True)
        update.effective_message.reply_to_message.text = "full long message here"
        quote = MagicMock()
        quote.text = "partial quote"
        update.effective_message.reply_to_message.quote = quote
        self.assertEqual(_extract_reply_context(update), "partial quote")

    def test_render_group_mentions_resolves_unique_member(self) -> None:
        from analyst.delivery.bot import _render_group_mentions

        members = [SimpleNamespace(user_id="42", display_name="Alice Zhang")]
        rendered, entities = _render_group_mentions("ask @[Alice Zhang] to check", members)

        self.assertEqual(rendered, "ask @Alice Zhang to check")
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0].user.id, 42)
        self.assertEqual(entities[0].offset, 4)
        self.assertEqual(entities[0].length, len("@Alice Zhang"))

    def test_render_group_mentions_leaves_ambiguous_member_plain(self) -> None:
        from analyst.delivery.bot import _render_group_mentions

        members = [
            SimpleNamespace(user_id="42", display_name="Alice"),
            SimpleNamespace(user_id="84", display_name="Alice"),
        ]
        rendered, entities = _render_group_mentions("ask @[Alice] to check", members)

        self.assertEqual(rendered, "ask @Alice to check")
        self.assertEqual(entities, [])

    async def test_group_reply_text_uses_telegram_entities_for_mentions(self) -> None:
        from analyst.delivery.bot import _make_message_handler
        from analyst.delivery.sales_chat import SalesChatReply
        from analyst.memory import ClientProfileUpdate

        mention_entity = MagicMock()
        mention_entity.type = "mention"
        entities = {mention_entity: "@testbot"}
        self.mock_store.list_group_members.return_value = [
            SimpleNamespace(
                user_id="42",
                display_name="Alice",
                role_in_group="",
                personality_notes="",
                first_seen_at="",
                last_seen_at="",
                message_count=3,
            )
        ]
        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        update, context = self._make_update(
            text="@testbot who should own this?",
            chat_type="supergroup",
            entities=entities,
        )

        with patch("analyst.delivery.bot.build_group_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction") as record_mock, \
             patch(
                 "analyst.delivery.bot._chat_reply",
                 new=AsyncMock(
                     return_value=SalesChatReply(
                         text="@[Alice] please take this one.",
                         profile_update=ClientProfileUpdate(),
                     )
                 ),
             ):
            await handler(update, context)

        reply_kwargs = update.effective_message.reply_text.call_args.kwargs
        self.assertEqual(reply_kwargs["text"], "@Alice please take this one.")
        self.assertEqual(len(reply_kwargs["entities"]), 1)
        self.assertEqual(reply_kwargs["entities"][0].user.id, 42)
        self.assertEqual(
            record_mock.call_args.kwargs["assistant_text"],
            "@Alice please take this one.",
        )
        self.assertEqual(
            self.mock_store.append_group_message.call_args_list[-1].kwargs["content"],
            "@Alice please take this one.",
        )

    async def test_reply_context_enriches_llm_text(self) -> None:
        """When replying to a message, the LLM should receive enriched text."""
        from analyst.delivery.bot import _make_message_handler

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        update, context = self._make_update(
            text="can you elaborate?", chat_type="private", reply_to_bot=True,
        )
        update.effective_message.reply_to_message.text = "the market is up 3%"
        update.effective_message.reply_to_message.quote = None

        with patch("analyst.delivery.bot.build_chat_context", return_value="") as mock_ctx, \
             patch("analyst.delivery.bot.record_chat_interaction") as mock_record:
            await handler(update, context)

        # LLM should receive enriched text with reply context
        call_kwargs = self.mock_loop.run.call_args.kwargs
        self.assertIn("the market is up 3%", call_kwargs["user_prompt"])
        self.assertIn("can you elaborate?", call_kwargs["user_prompt"])

        # record_chat_interaction should use original text
        mock_record.assert_called_once()
        self.assertEqual(mock_record.call_args.kwargs["user_text"], "can you elaborate?")

    async def test_companion_reply_applies_schedule_update(self) -> None:
        from analyst.delivery.bot import _make_message_handler
        from analyst.delivery.sales_chat import SalesChatReply
        from analyst.memory import ClientProfileUpdate, CompanionScheduleUpdate

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        update, context = self._make_update(text="中午准备干嘛？", chat_type="private")

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.apply_companion_schedule_update") as schedule_mock, \
             patch("analyst.delivery.bot.record_chat_interaction"):
            with patch(
                "analyst.delivery.bot._chat_reply",
                new=AsyncMock(
                    return_value=SalesChatReply(
                        text="我应该去吃牛肉饭。",
                        profile_update=ClientProfileUpdate(),
                        schedule_update=CompanionScheduleUpdate(
                            revision_mode="set",
                            lunch_plan="beef rice",
                        ),
                    )
                ),
            ):
                await handler(update, context)

        schedule_mock.assert_called_once()
        self.assertEqual(schedule_mock.call_args.args[1].lunch_plan, "beef rice")

    async def test_no_reply_context_passes_original_text(self) -> None:
        """Without a reply, the LLM text should be the original message."""
        from analyst.delivery.bot import _make_message_handler

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)
        update, context = self._make_update(text="hello", chat_type="private")

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction"):
            await handler(update, context)

        call_kwargs = self.mock_loop.run.call_args.kwargs
        self.assertEqual(call_kwargs["user_prompt"], "hello")

    async def test_group_agent_history_shared(self) -> None:
        """Group history uses chat_data (shared) not user_data (per-user)."""
        from analyst.delivery.bot import _make_message_handler

        handler = _make_message_handler(self.mock_loop, self.mock_tools, self.mock_store)

        mention_entity = MagicMock()
        mention_entity.type = "mention"
        entities = {mention_entity: "@testbot"}

        update, context = self._make_update(
            text="@testbot hi", chat_type="supergroup", entities=entities,
        )

        with patch("analyst.delivery.bot.build_chat_context", return_value=""), \
             patch("analyst.delivery.bot.record_chat_interaction"):
            await handler(update, context)

        # History should be in chat_data, not user_data
        self.assertIn("agent_history", context.chat_data)
        self.assertNotIn("history", context.user_data)


if __name__ == "__main__":
    unittest.main()
