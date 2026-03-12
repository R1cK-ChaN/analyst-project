from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst.delivery.companion_schedule import (
    apply_companion_schedule_update,
    build_companion_schedule_context,
    companion_schedule_date,
)
from analyst.memory import (
    CompanionScheduleUpdate,
    extract_embedded_schedule_update,
    split_reply_and_profile_update,
)
from analyst.storage import SQLiteEngineStore


class CompanionScheduleParsingTest(unittest.TestCase):
    def test_reply_strips_schedule_update_and_parses_payload(self) -> None:
        raw = (
            "今晚应该会去吃饭。"
            "<schedule_update>{\"revision_mode\":\"set\",\"dinner_plan\":\"beef rice\"}</schedule_update>"
            "<profile_update>{}</profile_update>"
        )

        visible, profile_update = split_reply_and_profile_update(raw)
        schedule_update = extract_embedded_schedule_update(raw)

        self.assertEqual(visible, "今晚应该会去吃饭。")
        self.assertEqual(profile_update.to_dict()["notes"], None)
        self.assertEqual(schedule_update.dinner_plan, "beef rice")
        self.assertEqual(schedule_update.normalized_revision_mode(), "set")


class CompanionScheduleStoreTest(unittest.TestCase):
    def test_schedule_set_then_require_explicit_revise(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SQLiteEngineStore(db_path=Path(tmpdir) / "engine.db")
            now = datetime(2026, 3, 12, 4, 0, tzinfo=timezone.utc)

            first = apply_companion_schedule_update(
                store,
                CompanionScheduleUpdate(
                    revision_mode="set",
                    lunch_plan="beef rice",
                    current_plan="heading to lunch",
                ),
                now=now,
                routine_state="lunch",
            )
            self.assertEqual(first.lunch_plan, "beef rice")
            self.assertEqual(first.current_plan, "heading to lunch")
            self.assertEqual(first.routine_state_snapshot, "lunch")
            self.assertTrue(first.last_explicit_update_at)

            second = apply_companion_schedule_update(
                store,
                CompanionScheduleUpdate(
                    revision_mode="set",
                    lunch_plan="roasted pork rice",
                    current_plan="still heading out",
                ),
                now=now,
                routine_state="lunch",
            )
            self.assertEqual(second.lunch_plan, "beef rice")
            self.assertEqual(second.current_plan, "still heading out")

            third = apply_companion_schedule_update(
                store,
                CompanionScheduleUpdate(
                    revision_mode="revise",
                    lunch_plan="roasted pork rice",
                    revision_note="changed lunch plan explicitly",
                ),
                now=now,
                routine_state="lunch",
            )
            self.assertEqual(third.lunch_plan, "roasted pork rice")
            self.assertEqual(third.revision_note, "changed lunch plan explicitly")

            same_day = store.get_companion_daily_schedule(
                schedule_date=companion_schedule_date(now),
            )
            self.assertEqual(same_day.lunch_plan, "roasted pork rice")

    def test_schedule_context_renders_existing_day_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SQLiteEngineStore(db_path=Path(tmpdir) / "engine.db")
            now = datetime(2026, 3, 12, 2, 30, tzinfo=timezone.utc)
            store.upsert_companion_daily_schedule(
                schedule_date=companion_schedule_date(now),
                lunch_plan="beef rice",
                dinner_plan="hotpot",
                current_plan="at desk",
                next_plan="head out for lunch",
            )

            rendered = build_companion_schedule_context(
                store,
                now=now,
                routine_state="work",
            )

            self.assertIn("lunch_plan: beef rice", rendered)
            self.assertIn("dinner_plan: hotpot", rendered)
            self.assertIn("current_plan: at desk", rendered)
            self.assertIn("routine_state: work", rendered)


if __name__ == "__main__":
    unittest.main()
