"""Tests for delivery.bot_group_chat and delivery.companion_reminders."""

from __future__ import annotations

import sys
import unittest
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from telegram import MessageEntity, User

from analyst.delivery.bot_constants import (
    MAX_GROUP_CONTEXT_CHARS,
    MAX_GROUP_CONTEXT_MESSAGES,
)
from analyst.delivery.bot_group_chat import (
    _append_group_buffer,
    _build_group_member_lookup,
    _extract_message_text,
    _extract_reply_context,
    _get_group_buffer,
    _is_bot_mentioned,
    _is_group_chat,
    _is_reply_to_bot,
    _normalize_group_member_name,
    _render_group_context,
    _render_group_mentions,
    _should_reply_in_group,
    _strip_bot_mention,
)
from analyst.delivery.companion_reminders import (
    _infer_reminder_language,
    _normalize_reminder_due_at,
    apply_companion_reminder_update,
    render_companion_reminder_message,
)


# ---------------------------------------------------------------------------
# Helpers for building mock Telegram objects
# ---------------------------------------------------------------------------


def _make_context(bot_username: str = "testbot", bot_id: int = 100) -> MagicMock:
    ctx = MagicMock()
    ctx.bot.username = bot_username
    ctx.bot.id = bot_id
    ctx.chat_data = {}
    return ctx


def _make_update(
    *,
    chat_type: str = "private",
    text: str | None = None,
    caption: str | None = None,
    entities: dict[MessageEntity, str] | None = None,
    caption_entities: dict[MessageEntity, str] | None = None,
    reply_to_message: Any | None = None,
    from_user: User | None = None,
) -> MagicMock:
    update = MagicMock()
    update.effective_chat.type = chat_type

    message = MagicMock()
    message.text = text
    message.caption = caption
    message.reply_to_message = reply_to_message

    # parse_entities / parse_caption_entities
    message.parse_entities.return_value = entities or {}
    message.parse_caption_entities.return_value = caption_entities or {}

    update.effective_message = message
    update.effective_user = from_user
    return update


@dataclass
class _FakeMember:
    display_name: str = ""
    user_id: Any = ""


# ===========================================================================
# bot_group_chat tests
# ===========================================================================


class TestIsGroupChat(unittest.TestCase):
    def test_group_type(self) -> None:
        update = _make_update(chat_type="group")
        self.assertTrue(_is_group_chat(update))

    def test_supergroup_type(self) -> None:
        update = _make_update(chat_type="supergroup")
        self.assertTrue(_is_group_chat(update))

    def test_private_type(self) -> None:
        update = _make_update(chat_type="private")
        self.assertFalse(_is_group_chat(update))

    def test_channel_type(self) -> None:
        update = _make_update(chat_type="channel")
        self.assertFalse(_is_group_chat(update))

    def test_none_chat(self) -> None:
        update = MagicMock()
        update.effective_chat = None
        self.assertFalse(_is_group_chat(update))


class TestIsBotMentioned(unittest.TestCase):
    def test_at_mention_match(self) -> None:
        entity = MessageEntity(type=MessageEntity.MENTION, offset=0, length=8)
        update = _make_update(
            text="@testbot hello",
            entities={entity: "@testbot"},
        )
        ctx = _make_context(bot_username="testbot")
        self.assertTrue(_is_bot_mentioned(update, ctx))

    def test_at_mention_case_insensitive(self) -> None:
        entity = MessageEntity(type=MessageEntity.MENTION, offset=0, length=8)
        update = _make_update(
            text="@TestBot hello",
            entities={entity: "@TestBot"},
        )
        ctx = _make_context(bot_username="testbot")
        self.assertTrue(_is_bot_mentioned(update, ctx))

    def test_text_mention_match(self) -> None:
        bot_user = User(id=100, first_name="Bot", is_bot=True)
        entity = MessageEntity(
            type=MessageEntity.TEXT_MENTION,
            offset=0,
            length=3,
            user=bot_user,
        )
        update = _make_update(
            text="Bot hello",
            entities={entity: "Bot"},
        )
        ctx = _make_context(bot_id=100)
        self.assertTrue(_is_bot_mentioned(update, ctx))

    def test_text_mention_wrong_user(self) -> None:
        other_user = User(id=999, first_name="Other", is_bot=False)
        entity = MessageEntity(
            type=MessageEntity.TEXT_MENTION,
            offset=0,
            length=5,
            user=other_user,
        )
        update = _make_update(
            text="Other hello",
            entities={entity: "Other"},
        )
        ctx = _make_context(bot_id=100)
        self.assertFalse(_is_bot_mentioned(update, ctx))

    def test_no_mention(self) -> None:
        update = _make_update(text="hello world")
        ctx = _make_context()
        self.assertFalse(_is_bot_mentioned(update, ctx))

    def test_none_message(self) -> None:
        update = MagicMock()
        update.effective_message = None
        ctx = _make_context()
        self.assertFalse(_is_bot_mentioned(update, ctx))

    def test_caption_mention(self) -> None:
        entity = MessageEntity(type=MessageEntity.MENTION, offset=0, length=8)
        update = _make_update(
            caption="@testbot check this image",
            caption_entities={entity: "@testbot"},
        )
        ctx = _make_context(bot_username="testbot")
        self.assertTrue(_is_bot_mentioned(update, ctx))


class TestIsReplyToBot(unittest.TestCase):
    def test_reply_to_bot(self) -> None:
        reply_msg = MagicMock()
        reply_msg.from_user = User(id=100, first_name="Bot", is_bot=True)
        update = _make_update(reply_to_message=reply_msg)
        ctx = _make_context(bot_id=100)
        self.assertTrue(_is_reply_to_bot(update, ctx))

    def test_reply_to_other_user(self) -> None:
        reply_msg = MagicMock()
        reply_msg.from_user = User(id=999, first_name="Other", is_bot=False)
        update = _make_update(reply_to_message=reply_msg)
        ctx = _make_context(bot_id=100)
        self.assertFalse(_is_reply_to_bot(update, ctx))

    def test_no_reply(self) -> None:
        update = _make_update()
        update.effective_message.reply_to_message = None
        ctx = _make_context(bot_id=100)
        self.assertFalse(_is_reply_to_bot(update, ctx))

    def test_none_message(self) -> None:
        update = MagicMock()
        update.effective_message = None
        ctx = _make_context()
        self.assertFalse(_is_reply_to_bot(update, ctx))


class TestShouldReplyInGroup(unittest.TestCase):
    def test_mentioned_triggers_reply(self) -> None:
        entity = MessageEntity(type=MessageEntity.MENTION, offset=0, length=8)
        update = _make_update(
            text="@testbot yo",
            entities={entity: "@testbot"},
        )
        update.effective_message.reply_to_message = None
        ctx = _make_context(bot_username="testbot", bot_id=100)
        self.assertTrue(_should_reply_in_group(update, ctx))

    def test_reply_to_bot_triggers_reply(self) -> None:
        reply_msg = MagicMock()
        reply_msg.from_user = User(id=100, first_name="Bot", is_bot=True)
        update = _make_update(reply_to_message=reply_msg)
        ctx = _make_context(bot_id=100)
        self.assertTrue(_should_reply_in_group(update, ctx))

    def test_neither_mention_nor_reply(self) -> None:
        update = _make_update(text="hello world")
        update.effective_message.reply_to_message = None
        ctx = _make_context()
        self.assertFalse(_should_reply_in_group(update, ctx))


class TestExtractReplyContext(unittest.TestCase):
    def test_extract_text_reply(self) -> None:
        reply_msg = MagicMock()
        reply_msg.text = "quoted text"
        reply_msg.caption = None
        reply_msg.quote = None
        update = _make_update(reply_to_message=reply_msg)
        self.assertEqual(_extract_reply_context(update), "quoted text")

    def test_extract_caption_reply(self) -> None:
        reply_msg = MagicMock()
        reply_msg.text = None
        reply_msg.caption = "image caption"
        reply_msg.quote = None
        update = _make_update(reply_to_message=reply_msg)
        self.assertEqual(_extract_reply_context(update), "image caption")

    def test_extract_partial_quote(self) -> None:
        reply_msg = MagicMock()
        reply_msg.text = "full text"
        reply_msg.caption = None
        quote = SimpleNamespace(text="partial")
        reply_msg.quote = quote
        update = _make_update(reply_to_message=reply_msg)
        self.assertEqual(_extract_reply_context(update), "partial")

    def test_no_reply(self) -> None:
        update = _make_update()
        update.effective_message.reply_to_message = None
        self.assertIsNone(_extract_reply_context(update))

    def test_none_message(self) -> None:
        update = MagicMock()
        update.effective_message = None
        self.assertIsNone(_extract_reply_context(update))


class TestStripBotMention(unittest.TestCase):
    def test_strip_mention_from_text(self) -> None:
        result = _strip_bot_mention("@testbot hello there", "testbot")
        self.assertEqual(result, "hello there")

    def test_strip_case_insensitive(self) -> None:
        result = _strip_bot_mention("@TestBot hello", "testbot")
        self.assertEqual(result, "hello")

    def test_no_mention_unchanged(self) -> None:
        result = _strip_bot_mention("hello there", "testbot")
        self.assertEqual(result, "hello there")

    def test_strip_only_bot_mention(self) -> None:
        result = _strip_bot_mention("@testbot", "testbot")
        self.assertEqual(result, "")


class TestExtractMessageText(unittest.TestCase):
    def test_extract_text(self) -> None:
        msg = SimpleNamespace(text="hello world", caption=None)
        self.assertEqual(_extract_message_text(msg), "hello world")

    def test_extract_caption(self) -> None:
        msg = SimpleNamespace(text=None, caption="  image caption  ")
        self.assertEqual(_extract_message_text(msg), "image caption")

    def test_neither_text_nor_caption(self) -> None:
        msg = SimpleNamespace(text=None, caption=None)
        self.assertEqual(_extract_message_text(msg), "")

    def test_whitespace_stripped(self) -> None:
        msg = SimpleNamespace(text="  spaced  ", caption=None)
        self.assertEqual(_extract_message_text(msg), "spaced")


class TestGroupBuffer(unittest.TestCase):
    def test_get_empty_buffer(self) -> None:
        ctx = _make_context()
        buf = _get_group_buffer(ctx, "thread_1")
        self.assertEqual(buf, [])

    def test_append_and_retrieve(self) -> None:
        ctx = _make_context()
        _append_group_buffer(ctx, "thread_1", "Alice", "hello")
        buf = _get_group_buffer(ctx, "thread_1")
        self.assertEqual(len(buf), 1)
        self.assertEqual(buf[0]["name"], "Alice")
        self.assertEqual(buf[0]["text"], "hello")
        self.assertEqual(buf[0]["role"], "user")

    def test_thread_isolation(self) -> None:
        ctx = _make_context()
        _append_group_buffer(ctx, "thread_1", "Alice", "msg1")
        _append_group_buffer(ctx, "thread_2", "Bob", "msg2")
        self.assertEqual(len(_get_group_buffer(ctx, "thread_1")), 1)
        self.assertEqual(len(_get_group_buffer(ctx, "thread_2")), 1)
        self.assertEqual(_get_group_buffer(ctx, "thread_1")[0]["name"], "Alice")
        self.assertEqual(_get_group_buffer(ctx, "thread_2")[0]["name"], "Bob")

    def test_trim_to_max(self) -> None:
        ctx = _make_context()
        for i in range(MAX_GROUP_CONTEXT_MESSAGES + 10):
            _append_group_buffer(ctx, "t", "user", f"msg_{i}")
        buf = _get_group_buffer(ctx, "t")
        self.assertEqual(len(buf), MAX_GROUP_CONTEXT_MESSAGES)
        # The earliest messages should have been trimmed; last message is the newest
        self.assertEqual(buf[-1]["text"], f"msg_{MAX_GROUP_CONTEXT_MESSAGES + 9}")

    def test_custom_role(self) -> None:
        ctx = _make_context()
        _append_group_buffer(ctx, "t", "Bot", "reply", role="assistant")
        buf = _get_group_buffer(ctx, "t")
        self.assertEqual(buf[0]["role"], "assistant")


class TestRenderGroupContext(unittest.TestCase):
    def test_basic_render(self) -> None:
        ctx = _make_context()
        _append_group_buffer(ctx, "t", "Alice", "hi")
        _append_group_buffer(ctx, "t", "Bob", "yo")
        rendered = _render_group_context(ctx, "t")
        self.assertIn("Alice: hi", rendered)
        self.assertIn("Bob: yo", rendered)

    def test_char_budget_truncation(self) -> None:
        ctx = _make_context()
        # Insert messages that together exceed the char budget
        long_text = "x" * (MAX_GROUP_CONTEXT_CHARS // 2 + 1)
        _append_group_buffer(ctx, "t", "A", long_text)
        _append_group_buffer(ctx, "t", "B", long_text)
        _append_group_buffer(ctx, "t", "C", long_text)
        rendered = _render_group_context(ctx, "t")
        # The total rendered text must not exceed the char budget
        self.assertLessEqual(len(rendered), MAX_GROUP_CONTEXT_CHARS)

    def test_most_recent_preferred(self) -> None:
        ctx = _make_context()
        # Fill with enough messages that the oldest will be dropped by char budget
        long_text = "x" * (MAX_GROUP_CONTEXT_CHARS - 20)
        _append_group_buffer(ctx, "t", "Old", long_text)
        _append_group_buffer(ctx, "t", "New", "short")
        rendered = _render_group_context(ctx, "t")
        # "New: short" should be in the result since it's newest and added first
        self.assertIn("New: short", rendered)

    def test_empty_buffer(self) -> None:
        ctx = _make_context()
        self.assertEqual(_render_group_context(ctx, "t"), "")


class TestNormalizeGroupMemberName(unittest.TestCase):
    def test_basic_normalization(self) -> None:
        self.assertEqual(_normalize_group_member_name("  Alice  "), "alice")

    def test_collapse_whitespace(self) -> None:
        self.assertEqual(_normalize_group_member_name("Alice   Bob"), "alice bob")

    def test_casefold(self) -> None:
        self.assertEqual(_normalize_group_member_name("ALICE"), "alice")

    def test_none_input(self) -> None:
        self.assertEqual(_normalize_group_member_name(None), "")

    def test_empty_input(self) -> None:
        self.assertEqual(_normalize_group_member_name(""), "")


class TestBuildGroupMemberLookup(unittest.TestCase):
    def test_basic_lookup(self) -> None:
        members = [_FakeMember(display_name="Alice", user_id=1)]
        lookup = _build_group_member_lookup(members)
        self.assertIn("alice", lookup)
        self.assertEqual(lookup["alice"], ("Alice", 1))

    def test_ambiguous_name_removed(self) -> None:
        members = [
            _FakeMember(display_name="Alice", user_id=1),
            _FakeMember(display_name="Alice", user_id=2),
        ]
        lookup = _build_group_member_lookup(members)
        self.assertNotIn("alice", lookup)

    def test_same_user_id_not_ambiguous(self) -> None:
        members = [
            _FakeMember(display_name="Alice", user_id=1),
            _FakeMember(display_name="Alice", user_id=1),
        ]
        lookup = _build_group_member_lookup(members)
        self.assertIn("alice", lookup)

    def test_empty_name_skipped(self) -> None:
        members = [_FakeMember(display_name="", user_id=1)]
        lookup = _build_group_member_lookup(members)
        self.assertEqual(len(lookup), 0)

    def test_invalid_user_id_skipped(self) -> None:
        members = [_FakeMember(display_name="Alice", user_id="abc")]
        lookup = _build_group_member_lookup(members)
        self.assertEqual(len(lookup), 0)

    def test_multiple_members(self) -> None:
        members = [
            _FakeMember(display_name="Alice", user_id=1),
            _FakeMember(display_name="Bob", user_id=2),
        ]
        lookup = _build_group_member_lookup(members)
        self.assertEqual(len(lookup), 2)
        self.assertEqual(lookup["alice"], ("Alice", 1))
        self.assertEqual(lookup["bob"], ("Bob", 2))


class TestRenderGroupMentions(unittest.TestCase):
    def test_no_mentions_passthrough(self) -> None:
        text, entities = _render_group_mentions("hello world", [])
        self.assertEqual(text, "hello world")
        self.assertEqual(entities, [])

    def test_mention_resolved(self) -> None:
        members = [_FakeMember(display_name="Alice", user_id=42)]
        text, entities = _render_group_mentions("hi @[Alice] how are you", members)
        self.assertIn("@Alice", text)
        self.assertNotIn("@[Alice]", text)
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0].type, MessageEntity.TEXT_MENTION)
        self.assertEqual(entities[0].user.id, 42)

    def test_mention_unresolved_kept_as_at_name(self) -> None:
        members = []
        text, entities = _render_group_mentions("hi @[Unknown] there", members)
        self.assertIn("@Unknown", text)
        self.assertEqual(len(entities), 0)

    def test_multiple_mentions(self) -> None:
        members = [
            _FakeMember(display_name="Alice", user_id=1),
            _FakeMember(display_name="Bob", user_id=2),
        ]
        text, entities = _render_group_mentions("@[Alice] and @[Bob] check this", members)
        self.assertIn("@Alice", text)
        self.assertIn("@Bob", text)
        self.assertEqual(len(entities), 2)

    def test_entity_offsets_correct(self) -> None:
        members = [_FakeMember(display_name="Alice", user_id=42)]
        text, entities = _render_group_mentions("hi @[Alice] end", members)
        entity = entities[0]
        extracted = text[entity.offset : entity.offset + entity.length]
        self.assertEqual(extracted, "@Alice")


# ===========================================================================
# companion_reminders tests
# ===========================================================================


class TestInferReminderLanguage(unittest.TestCase):
    def test_chinese_text(self) -> None:
        self.assertEqual(_infer_reminder_language("记得开会"), "zh")

    def test_english_text(self) -> None:
        self.assertEqual(_infer_reminder_language("remember to call"), "en")

    def test_mixed_text_with_cjk(self) -> None:
        self.assertEqual(_infer_reminder_language("call 老板 at 3pm"), "zh")

    def test_empty_text(self) -> None:
        self.assertEqual(_infer_reminder_language(""), "en")


class TestNormalizeReminderDueAt(unittest.TestCase):
    def test_valid_iso_with_timezone(self) -> None:
        result = _normalize_reminder_due_at(
            "2026-06-01T10:00:00+08:00", timezone_name="Asia/Singapore"
        )
        self.assertIn("2026-06-01", result)
        # Result should be UTC ISO
        self.assertTrue(result.endswith("+00:00"))

    def test_naive_datetime_gets_default_tz(self) -> None:
        result = _normalize_reminder_due_at(
            "2026-06-01T10:00:00", timezone_name="Asia/Singapore"
        )
        # 10:00 SGT (UTC+8) => 02:00 UTC
        self.assertIn("02:00:00", result)

    def test_empty_input(self) -> None:
        self.assertEqual(
            _normalize_reminder_due_at("", timezone_name="Asia/Singapore"), ""
        )

    def test_invalid_input(self) -> None:
        self.assertEqual(
            _normalize_reminder_due_at("not-a-date", timezone_name="Asia/Singapore"),
            "",
        )

    def test_invalid_timezone_falls_back(self) -> None:
        # Should fall back to Asia/Singapore and still parse the date
        result = _normalize_reminder_due_at(
            "2026-06-01T10:00:00", timezone_name="Invalid/Zone"
        )
        self.assertIn("2026-06-01", result)


class TestRenderCompanionReminderMessage(unittest.TestCase):
    def _make_record(self, preferred_language: str = "") -> Any:
        return SimpleNamespace(
            reminder_id=1,
            client_id="c1",
            channel="ch1",
            thread_id="t1",
            reminder_text="Take medicine",
            due_at="2026-06-01T10:00:00+00:00",
            timezone_name="Asia/Singapore",
            status="pending",
            created_at="2026-05-01T00:00:00+00:00",
            sent_at="",
            metadata={"preferred_language": preferred_language},
        )

    def test_english_rendering(self) -> None:
        record = self._make_record(preferred_language="en")
        msg = render_companion_reminder_message(record)
        self.assertEqual(msg, "Reminder: Take medicine")

    def test_chinese_rendering_default(self) -> None:
        record = self._make_record(preferred_language="zh")
        msg = render_companion_reminder_message(record)
        self.assertEqual(msg, "提醒你一下：Take medicine")

    def test_no_language_defaults_to_chinese(self) -> None:
        record = self._make_record(preferred_language="")
        msg = render_companion_reminder_message(record)
        self.assertTrue(msg.startswith("提醒你一下"))


class TestApplyCompanionReminderUpdate(unittest.TestCase):
    def _make_store(self) -> MagicMock:
        store = MagicMock()
        store.create_companion_reminder.return_value = SimpleNamespace(
            reminder_id=1,
            client_id="c1",
            channel="ch1",
            thread_id="t1",
            reminder_text="test reminder",
            due_at="2026-06-01T02:00:00+00:00",
            timezone_name="Asia/Singapore",
            status="pending",
            created_at="2026-05-01T00:00:00+00:00",
            sent_at="",
            metadata={"preferred_language": "en"},
        )
        return store

    def _make_update_obj(
        self,
        *,
        reminder_text: str | None = "test reminder",
        due_at: str | None = "2026-06-01T10:00:00",
        timezone_name: str | None = "Asia/Singapore",
    ) -> Any:
        obj = SimpleNamespace(
            reminder_text=reminder_text,
            due_at=due_at,
            timezone_name=timezone_name,
        )
        obj.has_changes = lambda: bool(reminder_text and due_at)
        return obj

    def test_valid_future_reminder(self) -> None:
        store = self._make_store()
        update = self._make_update_obj()
        now = datetime(2026, 3, 17, 0, 0, 0, tzinfo=timezone.utc)
        result = apply_companion_reminder_update(
            store,
            update,
            client_id="c1",
            channel_id="ch1",
            thread_id="t1",
            now=now,
        )
        self.assertIsNotNone(result)
        store.create_companion_reminder.assert_called_once()

    def test_past_due_at_rejected(self) -> None:
        store = self._make_store()
        update = self._make_update_obj(due_at="2020-01-01T10:00:00")
        now = datetime(2026, 3, 17, 0, 0, 0, tzinfo=timezone.utc)
        result = apply_companion_reminder_update(
            store,
            update,
            client_id="c1",
            channel_id="ch1",
            thread_id="t1",
            now=now,
        )
        self.assertIsNone(result)
        store.create_companion_reminder.assert_not_called()

    def test_no_changes_returns_none(self) -> None:
        store = self._make_store()
        update = self._make_update_obj(reminder_text=None, due_at=None)
        result = apply_companion_reminder_update(
            store,
            update,
            client_id="c1",
            channel_id="ch1",
            thread_id="t1",
        )
        self.assertIsNone(result)
        store.create_companion_reminder.assert_not_called()

    def test_empty_reminder_text_returns_none(self) -> None:
        store = self._make_store()
        update = self._make_update_obj(reminder_text="   ")
        # has_changes will return False because "   ".strip() is falsy, but
        # the original code checks update.reminder_text (before strip). Let's
        # set it so has_changes returns True but text is whitespace-only.
        update.has_changes = lambda: True
        now = datetime(2026, 3, 17, 0, 0, 0, tzinfo=timezone.utc)
        result = apply_companion_reminder_update(
            store,
            update,
            client_id="c1",
            channel_id="ch1",
            thread_id="t1",
            now=now,
        )
        self.assertIsNone(result)
        store.create_companion_reminder.assert_not_called()

    def test_timezone_applied_to_naive_due_at(self) -> None:
        store = self._make_store()
        # due_at has no tz info, should use Singapore (UTC+8)
        update = self._make_update_obj(
            due_at="2026-06-01T10:00:00",
            timezone_name="Asia/Singapore",
        )
        now = datetime(2026, 3, 17, 0, 0, 0, tzinfo=timezone.utc)
        apply_companion_reminder_update(
            store,
            update,
            client_id="c1",
            channel_id="ch1",
            thread_id="t1",
            now=now,
        )
        call_kwargs = store.create_companion_reminder.call_args
        due_at_arg = call_kwargs.kwargs.get("due_at") or call_kwargs[1].get("due_at")
        # 10:00 Singapore (UTC+8) -> 02:00 UTC
        self.assertIn("02:00:00", due_at_arg)

    def test_preferred_language_passed_through(self) -> None:
        store = self._make_store()
        update = self._make_update_obj(reminder_text="call boss")
        now = datetime(2026, 3, 17, 0, 0, 0, tzinfo=timezone.utc)
        apply_companion_reminder_update(
            store,
            update,
            client_id="c1",
            channel_id="ch1",
            thread_id="t1",
            now=now,
            preferred_language="en",
        )
        call_kwargs = store.create_companion_reminder.call_args
        metadata = call_kwargs.kwargs.get("metadata") or call_kwargs[1].get("metadata")
        self.assertEqual(metadata["preferred_language"], "en")

    def test_language_inferred_when_not_provided(self) -> None:
        store = self._make_store()
        update = self._make_update_obj(reminder_text="记得开会")
        now = datetime(2026, 3, 17, 0, 0, 0, tzinfo=timezone.utc)
        apply_companion_reminder_update(
            store,
            update,
            client_id="c1",
            channel_id="ch1",
            thread_id="t1",
            now=now,
            preferred_language="",
        )
        call_kwargs = store.create_companion_reminder.call_args
        metadata = call_kwargs.kwargs.get("metadata") or call_kwargs[1].get("metadata")
        self.assertEqual(metadata["preferred_language"], "zh")

    def test_now_defaults_to_utc_now(self) -> None:
        store = self._make_store()
        # Use a due_at far in the future so it always passes
        update = self._make_update_obj(due_at="2099-12-31T23:59:59+00:00")
        result = apply_companion_reminder_update(
            store,
            update,
            client_id="c1",
            channel_id="ch1",
            thread_id="t1",
        )
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
