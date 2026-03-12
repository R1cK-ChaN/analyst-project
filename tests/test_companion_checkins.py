from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst.contracts import utc_now
from analyst.delivery.bot import (
    _first_reply_delay_seconds,
    _reply_timing_bucket,
    _run_companion_checkins_job,
)
from analyst.delivery.sales_chat import system_prompt_with_memory
from analyst.delivery.sales_chat import ChatReply
from analyst.memory import ClientProfileUpdate
from analyst.storage import SQLiteEngineStore


class CompanionTimingHelperTest(unittest.TestCase):
    def test_reply_timing_bucket_classifies_instant_normal_emotional_and_deep_story(self) -> None:
        self.assertEqual(_reply_timing_bucket("ok"), "instant")
        self.assertEqual(_reply_timing_bucket("how was your afternoon"), "normal")
        self.assertEqual(_reply_timing_bucket("i had a rough day and i feel overwhelmed"), "emotional")
        self.assertEqual(
            _reply_timing_bucket("line1\nline2\nline3\nline4"),
            "deep_story",
        )

    def test_first_reply_delay_increases_with_heavier_emotional_weight(self) -> None:
        instant_delay = _first_reply_delay_seconds("ok")
        normal_delay = _first_reply_delay_seconds("how was your afternoon")
        emotional_delay = _first_reply_delay_seconds("i had a rough day and i feel overwhelmed")
        deep_delay = _first_reply_delay_seconds("x" * 260)

        self.assertLess(instant_delay, normal_delay)
        self.assertLess(normal_delay, emotional_delay)
        self.assertLess(emotional_delay, deep_delay)

    def test_proactive_companion_prompt_adds_non_manipulative_guardrails(self) -> None:
        prompt = system_prompt_with_memory(
            "",
            persona_mode="companion",
            proactive_kind="follow_up",
        )
        self.assertIn("主动发起一条 companion check-in", prompt)
        self.assertIn("不要 guilt-trip", prompt)
        self.assertIn("不要主动聊市场", prompt)


class CompanionCheckInStoreTest(unittest.TestCase):
    def test_default_state_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteEngineStore(db_path=Path(td) / "test.db")
            state = store.get_companion_checkin_state(
                client_id="u1",
                channel="telegram:1",
                thread_id="main",
            )
        self.assertFalse(state.enabled)
        self.assertEqual(state.pending_kind, "")

    def test_enable_schedule_and_mark_sent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteEngineStore(db_path=Path(td) / "test.db")
            store.set_companion_checkins_enabled(
                client_id="u1",
                channel="telegram:1",
                thread_id="main",
                enabled=True,
            )
            due_at = utc_now().isoformat()
            store.schedule_companion_checkin(
                client_id="u1",
                channel="telegram:1",
                thread_id="main",
                kind="follow_up",
                due_at=due_at,
            )
            due = store.list_due_companion_checkins(now_iso=due_at)
            self.assertEqual(len(due), 1)
            state = store.mark_companion_checkin_sent(
                client_id="u1",
                channel="telegram:1",
                thread_id="main",
                kind="follow_up",
                sent_at=due_at,
                cooldown_until=(utc_now()).isoformat(),
            )
        self.assertEqual(state.pending_kind, "")
        self.assertEqual(state.last_sent_kind, "follow_up")


class CompanionCheckInJobTest(unittest.IsolatedAsyncioTestCase):
    async def test_job_sends_due_checkin_and_marks_state_sent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteEngineStore(db_path=Path(td) / "test.db")
            store.set_companion_checkins_enabled(
                client_id="u1",
                channel="telegram:123",
                thread_id="main",
                enabled=True,
            )
            store.schedule_companion_checkin(
                client_id="u1",
                channel="telegram:123",
                thread_id="main",
                kind="follow_up",
                due_at=utc_now().isoformat(),
            )
            context = SimpleNamespace(
                job=SimpleNamespace(data={"store": store, "agent_loop": MagicMock()}),
                bot=MagicMock(),
            )
            async def fake_to_thread(func, *args, **kwargs):
                return func(*args, **kwargs)

            with patch("analyst.delivery.bot._is_within_checkin_send_window", return_value=True), \
                 patch("analyst.delivery.bot.asyncio.to_thread", side_effect=fake_to_thread), \
                 patch("analyst.delivery.bot.build_chat_context", return_value=""), \
                 patch(
                     "analyst.delivery.bot.generate_proactive_companion_reply",
                     return_value=ChatReply(
                         text="hey[SPLIT]just checking in",
                         profile_update=ClientProfileUpdate(),
                     ),
                 ), \
                 patch("analyst.delivery.bot._send_bot_bubbles", new=AsyncMock()) as send_mock:
                await _run_companion_checkins_job(context)

            state = store.get_companion_checkin_state(
                client_id="u1",
                channel="telegram:123",
                thread_id="main",
            )
            self.assertEqual(state.pending_kind, "")
            self.assertEqual(state.last_sent_kind, "follow_up")
            send_mock.assert_awaited_once()
            deliveries = store.list_recent_deliveries(client_id="u1", channel="telegram:123", thread_id="main", limit=1)
            self.assertEqual(deliveries[0].source_type, "companion_checkin")

    async def test_job_failure_reschedules_same_day_retry(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = SQLiteEngineStore(db_path=Path(td) / "test.db")
            store.set_companion_checkins_enabled(
                client_id="u1",
                channel="telegram:123",
                thread_id="main",
                enabled=True,
            )
            store.schedule_companion_checkin(
                client_id="u1",
                channel="telegram:123",
                thread_id="main",
                kind="follow_up",
                due_at=utc_now().isoformat(),
            )
            context = SimpleNamespace(
                job=SimpleNamespace(data={"store": store, "agent_loop": MagicMock()}),
                bot=MagicMock(),
            )
            retry_due = utc_now()
            async def fake_to_thread(func, *args, **kwargs):
                return func(*args, **kwargs)

            with patch("analyst.delivery.bot._is_within_checkin_send_window", return_value=True), \
                 patch("analyst.delivery.bot.asyncio.to_thread", side_effect=fake_to_thread), \
                 patch(
                     "analyst.delivery.bot.generate_proactive_companion_reply",
                     side_effect=RuntimeError("boom"),
                 ), \
                 patch("analyst.delivery.bot._same_day_retry_due", return_value=retry_due):
                await _run_companion_checkins_job(context)

            state = store.get_companion_checkin_state(
                client_id="u1",
                channel="telegram:123",
                thread_id="main",
            )
            self.assertEqual(state.pending_kind, "follow_up")
            self.assertEqual(state.retry_count, 1)
            self.assertEqual(state.pending_due_at, retry_due.isoformat())
