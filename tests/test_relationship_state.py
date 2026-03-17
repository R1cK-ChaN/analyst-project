from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst.storage import SQLiteEngineStore
from analyst.storage.sqlite_records import (
    CompanionRelationshipStateRecord,
    NicknameEntry,
)
from analyst.memory.profile import RelationshipSignalUpdate
from analyst.memory.relationship import (
    compute_relationship_update,
    extract_nicknames_from_facts,
    _compute_emotional_trend,
    _update_streak,
    _maybe_transition_stage,
)
from analyst.memory.service import (
    _render_companion_profile,
    _detect_personal_sharing,
    _is_late_night_utc8,
)
from analyst.storage.sqlite_records import ClientProfileRecord


def _make_store() -> SQLiteEngineStore:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    store = SQLiteEngineStore(db_path=Path(tmp.name))
    return store


def _default_relationship(client_id: str = "u1") -> CompanionRelationshipStateRecord:
    return CompanionRelationshipStateRecord(
        client_id=client_id,
        intimacy_level=0.0,
        relationship_stage="stranger",
        tendency_friend=0.25,
        tendency_romantic=0.25,
        tendency_confidant=0.25,
        tendency_mentor=0.25,
        streak_days=0,
        total_turns=0,
        avg_session_turns=0.0,
        mood_history=[],
        nicknames=[],
        last_interaction_date="",
        last_stage_transition_at="",
        created_at="",
        updated_at="",
    )


def _default_profile(client_id: str = "u1") -> ClientProfileRecord:
    return ClientProfileRecord(
        client_id=client_id,
        preferred_language="zh",
        watchlist_topics=[],
        response_style="",
        risk_appetite="",
        investment_horizon="",
        institution_type="",
        risk_preference="",
        asset_focus=[],
        market_focus=[],
        expertise_level="",
        activity="",
        current_mood="",
        emotional_trend="",
        stress_level="",
        confidence="",
        notes="",
        personal_facts=[],
        last_active_at="",
        total_interactions=0,
        updated_at="",
    )


class TestDefaultRelationshipState(unittest.TestCase):
    def test_default_is_stranger(self):
        store = _make_store()
        rel = store.get_companion_relationship_state(client_id="unknown_user")
        self.assertEqual(rel.relationship_stage, "stranger")
        self.assertAlmostEqual(rel.intimacy_level, 0.0)
        self.assertAlmostEqual(rel.tendency_friend, 0.25)
        self.assertAlmostEqual(rel.tendency_romantic, 0.25)
        self.assertAlmostEqual(rel.tendency_confidant, 0.25)
        self.assertAlmostEqual(rel.tendency_mentor, 0.25)
        self.assertEqual(rel.streak_days, 0)
        self.assertEqual(rel.total_turns, 0)
        self.assertEqual(rel.mood_history, [])
        self.assertEqual(rel.nicknames, [])


class TestRelationshipUpdate(unittest.TestCase):
    def test_turns_and_intimacy_increment(self):
        current = _default_relationship()
        signal = RelationshipSignalUpdate(current_mood="calm")
        now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        updates = compute_relationship_update(current, signal=signal, now=now)

        self.assertEqual(updates["total_turns"], 1)
        self.assertGreater(updates["intimacy_level"], 0.0)
        self.assertEqual(updates["last_interaction_date"], "2026-03-17")
        self.assertEqual(updates["mood_history"], ["calm"])

    def test_personal_sharing_boosts_intimacy(self):
        current = _default_relationship()
        base_signal = RelationshipSignalUpdate(current_mood="calm")
        sharing_signal = RelationshipSignalUpdate(current_mood="calm", is_personal_sharing=True)
        now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)

        base_updates = compute_relationship_update(current, signal=base_signal, now=now)
        sharing_updates = compute_relationship_update(current, signal=sharing_signal, now=now)

        self.assertGreater(sharing_updates["intimacy_level"], base_updates["intimacy_level"])


class TestStreak(unittest.TestCase):
    def test_streak_consecutive_days(self):
        result = _update_streak(3, "2026-03-16", "2026-03-17")
        self.assertEqual(result, 4)

    def test_streak_resets_on_gap(self):
        result = _update_streak(5, "2026-03-14", "2026-03-17")
        self.assertEqual(result, 1)

    def test_streak_same_day_no_change(self):
        result = _update_streak(3, "2026-03-17", "2026-03-17")
        self.assertEqual(result, 3)

    def test_streak_first_interaction(self):
        result = _update_streak(0, "", "2026-03-17")
        self.assertEqual(result, 1)


class TestStageTransitions(unittest.TestCase):
    def test_stranger_to_acquaintance(self):
        now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        result = _maybe_transition_stage("stranger", 0.15, "", now)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "acquaintance")

    def test_below_threshold_no_transition(self):
        now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        result = _maybe_transition_stage("stranger", 0.10, "", now)
        self.assertIsNone(result)

    def test_acquaintance_to_familiar(self):
        now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        result = _maybe_transition_stage("acquaintance", 0.40, "", now)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "familiar")

    def test_familiar_to_close(self):
        now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        result = _maybe_transition_stage("familiar", 0.70, "", now)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "close")

    def test_cooldown_blocks_transition(self):
        recent = datetime(2026, 3, 17, 10, 0, tzinfo=timezone.utc)
        now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)  # Only 2h later
        result = _maybe_transition_stage("stranger", 0.15, recent.isoformat(), now)
        self.assertIsNone(result)

    def test_cooldown_expired_allows_transition(self):
        old = datetime(2026, 3, 14, 10, 0, tzinfo=timezone.utc)
        now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)  # 3 days later
        result = _maybe_transition_stage("stranger", 0.15, old.isoformat(), now)
        self.assertIsNotNone(result)


class TestEmotionalTrend(unittest.TestCase):
    def test_improving(self):
        moods = ["anxious", "anxious", "anxious", "calm", "optimistic", "happy"]
        self.assertEqual(_compute_emotional_trend(moods), "improving")

    def test_declining(self):
        moods = ["happy", "optimistic", "calm", "anxious", "stressed", "sad"]
        self.assertEqual(_compute_emotional_trend(moods), "declining")

    def test_stable(self):
        moods = ["calm", "calm", "calm", "calm", "calm"]
        self.assertEqual(_compute_emotional_trend(moods), "stable")

    def test_insufficient_data(self):
        self.assertEqual(_compute_emotional_trend(["anxious"]), "")
        self.assertEqual(_compute_emotional_trend(["anxious", "calm"]), "")


class TestNicknames(unittest.TestCase):
    def test_extract_from_facts(self):
        facts = ["用户叫我小襄", "他最近在学做饭", "我叫他哥哥"]
        entries = extract_nicknames_from_facts(facts)
        self.assertEqual(len(entries), 2)
        ai_nick = [e for e in entries if e.target == "ai"]
        user_nick = [e for e in entries if e.target == "user"]
        self.assertEqual(len(ai_nick), 1)
        self.assertEqual(ai_nick[0].name, "小襄")
        self.assertEqual(len(user_nick), 1)
        self.assertEqual(user_nick[0].name, "哥哥")

    def test_nickname_roundtrip_in_store(self):
        store = _make_store()
        nicknames = [
            {"name": "小襄", "target": "ai", "created_by": "user", "frequency": 5, "accepted": True,
             "context": "", "sentiment": "playful"},
        ]
        store.update_companion_relationship_state(client_id="u1", nicknames=nicknames)
        rel = store.get_companion_relationship_state(client_id="u1")
        self.assertEqual(len(rel.nicknames), 1)
        self.assertEqual(rel.nicknames[0]["name"], "小襄")
        self.assertEqual(rel.nicknames[0]["frequency"], 5)


class TestNarrativeRendering(unittest.TestCase):
    def test_familiar_stage_instruction(self):
        rel = CompanionRelationshipStateRecord(
            client_id="u1",
            intimacy_level=0.5,
            relationship_stage="familiar",
            tendency_friend=0.4,
            tendency_romantic=0.2,
            tendency_confidant=0.2,
            tendency_mentor=0.2,
            streak_days=5,
            total_turns=87,
            avg_session_turns=8.0,
            mood_history=["calm", "calm", "calm"],
            nicknames=[],
            last_interaction_date="2026-03-17",
            last_stage_transition_at="",
            created_at="2026-03-01",
            updated_at="2026-03-17",
        )
        profile = _default_profile()
        lines = _render_companion_profile(profile, relationship=rel)
        rendered = "\n".join(lines)
        self.assertIn("familiar", rendered)
        self.assertIn("撒娇", rendered)
        self.assertIn("87轮", rendered)

    def test_no_relationship_fallback(self):
        profile = _default_profile()
        lines = _render_companion_profile(profile, relationship=None)
        # Should not crash, should return list
        self.assertIsInstance(lines, list)

    def test_stress_high_declining_shows_strategy(self):
        rel = CompanionRelationshipStateRecord(
            client_id="u1",
            intimacy_level=0.3,
            relationship_stage="acquaintance",
            tendency_friend=0.25,
            tendency_romantic=0.25,
            tendency_confidant=0.25,
            tendency_mentor=0.25,
            streak_days=2,
            total_turns=20,
            avg_session_turns=5.0,
            mood_history=["happy", "calm", "anxious", "stressed", "sad"],
            nicknames=[],
            last_interaction_date="2026-03-17",
            last_stage_transition_at="",
            created_at="2026-03-10",
            updated_at="2026-03-17",
        )
        profile = ClientProfileRecord(
            client_id="u1",
            preferred_language="zh",
            watchlist_topics=[],
            response_style="",
            risk_appetite="",
            investment_horizon="",
            institution_type="",
            risk_preference="",
            asset_focus=[],
            market_focus=[],
            expertise_level="",
            activity="",
            current_mood="stressed",
            emotional_trend="",
            stress_level="high",
            confidence="",
            notes="",
            personal_facts=["他养了一只猫"],
            last_active_at="2026-03-17T10:00:00+00:00",
            total_interactions=20,
            updated_at="2026-03-17",
        )
        lines = _render_companion_profile(profile, relationship=rel)
        rendered = "\n".join(lines)
        self.assertIn("declining", rendered)
        self.assertIn("共情", rendered)
        self.assertIn("你记得", rendered)
        self.assertIn("猫", rendered)

    def test_nickname_rendering(self):
        rel = CompanionRelationshipStateRecord(
            client_id="u1",
            intimacy_level=0.5,
            relationship_stage="familiar",
            tendency_friend=0.25,
            tendency_romantic=0.25,
            tendency_confidant=0.25,
            tendency_mentor=0.25,
            streak_days=3,
            total_turns=50,
            avg_session_turns=6.0,
            mood_history=[],
            nicknames=[{"name": "小襄", "target": "ai", "created_by": "user",
                       "frequency": 12, "accepted": True, "context": "", "sentiment": "playful"}],
            last_interaction_date="2026-03-17",
            last_stage_transition_at="",
            created_at="2026-03-01",
            updated_at="2026-03-17",
        )
        profile = _default_profile()
        lines = _render_companion_profile(profile, relationship=rel)
        rendered = "\n".join(lines)
        self.assertIn("小襄", rendered)
        self.assertIn("称呼", rendered)


class TestHelpers(unittest.TestCase):
    def test_detect_personal_sharing(self):
        self.assertTrue(_detect_personal_sharing("我最近跟女朋友吵架了"))
        self.assertTrue(_detect_personal_sharing("I feel so lonely"))
        self.assertFalse(_detect_personal_sharing("今天天气不错"))

    def test_is_late_night_utc8(self):
        # 23:30 UTC+8 = 15:30 UTC
        late = datetime(2026, 3, 17, 15, 30, tzinfo=timezone.utc)
        self.assertTrue(_is_late_night_utc8(late))
        # 10:00 UTC+8 = 02:00 UTC
        morning = datetime(2026, 3, 17, 2, 0, tzinfo=timezone.utc)
        self.assertFalse(_is_late_night_utc8(morning))


if __name__ == "__main__":
    unittest.main()
