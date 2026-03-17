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
    _apply_intimacy_decay,
    _compute_emotional_trend,
    _update_streak,
    _maybe_transition_stage,
    _update_tendencies,
    _bump_nickname_frequency,
    _normalize_tendencies,
)
from analyst.memory.service import (
    _render_companion_profile,
    _detect_personal_sharing,
    _detect_active_topic_category,
    _is_late_night_utc8,
)
from analyst.storage.sqlite_records import ClientProfileRecord


def _make_store() -> SQLiteEngineStore:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    store = SQLiteEngineStore(db_path=Path(tmp.name))
    return store


def _default_relationship(client_id: str = "u1", **overrides) -> CompanionRelationshipStateRecord:
    defaults = dict(
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
    defaults.update(overrides)
    return CompanionRelationshipStateRecord(**defaults)


def _default_profile(client_id: str = "u1", **overrides) -> ClientProfileRecord:
    defaults = dict(
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
    defaults.update(overrides)
    return ClientProfileRecord(**defaults)


def _mood_entry(mood: str, hours_ago: float = 0, ref: datetime | None = None) -> dict:
    """Helper to create timestamped mood entries."""
    ref = ref or datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
    at = ref - timedelta(hours=hours_ago)
    return {"mood": mood, "at": at.isoformat()}


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
        # mood_history is now timestamped dicts
        self.assertEqual(len(updates["mood_history"]), 1)
        self.assertEqual(updates["mood_history"][0]["mood"], "calm")

    def test_personal_sharing_boosts_intimacy(self):
        current = _default_relationship()
        base_signal = RelationshipSignalUpdate(current_mood="calm")
        sharing_signal = RelationshipSignalUpdate(current_mood="calm", is_personal_sharing=True)
        now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)

        base_updates = compute_relationship_update(current, signal=base_signal, now=now)
        sharing_updates = compute_relationship_update(current, signal=sharing_signal, now=now)

        self.assertGreater(sharing_updates["intimacy_level"], base_updates["intimacy_level"])


# ---- #1: Intimacy Decay ----

class TestIntimacyDecay(unittest.TestCase):
    def test_no_decay_same_day(self):
        result = _apply_intimacy_decay(0.5, "2026-03-17", "2026-03-17")
        self.assertAlmostEqual(result, 0.5)

    def test_no_decay_next_day(self):
        result = _apply_intimacy_decay(0.5, "2026-03-16", "2026-03-17")
        self.assertAlmostEqual(result, 0.5)

    def test_decay_after_3_days(self):
        # 3 days gap → 2 decay days (after 1-day grace) → -0.02
        result = _apply_intimacy_decay(0.5, "2026-03-14", "2026-03-17")
        self.assertAlmostEqual(result, 0.48)

    def test_decay_after_7_days(self):
        # 7 days gap → 6 decay days → -0.06
        result = _apply_intimacy_decay(0.5, "2026-03-10", "2026-03-17")
        self.assertAlmostEqual(result, 0.44)

    def test_decay_floors_at_zero(self):
        result = _apply_intimacy_decay(0.02, "2026-03-01", "2026-03-17")
        self.assertAlmostEqual(result, 0.0)

    def test_decay_in_full_update_flow(self):
        current = _default_relationship(
            intimacy_level=0.5, last_interaction_date="2026-03-10",
        )
        signal = RelationshipSignalUpdate(current_mood="calm")
        now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        updates = compute_relationship_update(current, signal=signal, now=now)
        # 6 decay days × 0.01 = 0.06 decay, then +0.003 base growth
        self.assertAlmostEqual(updates["intimacy_level"], 0.443, places=3)

    def test_stage_regression_on_heavy_decay(self):
        # familiar needs 0.40, regression at < 0.28 (0.40 * 0.7)
        now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        result = _maybe_transition_stage("familiar", 0.20, "", now)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "acquaintance")

    def test_no_regression_above_threshold(self):
        now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        result = _maybe_transition_stage("familiar", 0.35, "", now)
        self.assertIsNone(result)


# ---- #2: Tendency Distribution ----

class TestTendencyUpdates(unittest.TestCase):
    def test_emotional_topic_nudges_confidant(self):
        signal = RelationshipSignalUpdate(
            current_mood="sad", active_topic_category="mood / emotional",
        )
        tf, tr, tc, tm = _update_tendencies(0.25, 0.25, 0.25, 0.25, signal=signal)
        self.assertGreater(tc, 0.25)  # confidant increased
        self.assertAlmostEqual(tf + tr + tc + tm, 1.0, places=3)

    def test_banter_nudges_friend(self):
        signal = RelationshipSignalUpdate(
            current_mood="happy", active_topic_category="joke / banter",
        )
        tf, tr, tc, tm = _update_tendencies(0.25, 0.25, 0.25, 0.25, signal=signal)
        self.assertGreater(tf, 0.25)  # friend increased

    def test_work_topic_nudges_mentor(self):
        signal = RelationshipSignalUpdate(
            current_mood="calm", active_topic_category="work / office",
        )
        tf, tr, tc, tm = _update_tendencies(0.25, 0.25, 0.25, 0.25, signal=signal)
        self.assertGreater(tm, 0.25)  # mentor increased

    def test_late_night_nudges_romantic_and_confidant(self):
        signal = RelationshipSignalUpdate(
            current_mood="calm", is_late_night=True,
        )
        tf, tr, tc, tm = _update_tendencies(0.25, 0.25, 0.25, 0.25, signal=signal)
        self.assertGreater(tr, 0.25)  # romantic increased
        self.assertGreater(tc, 0.25)  # confidant increased

    def test_personal_sharing_nudges_confidant(self):
        signal = RelationshipSignalUpdate(
            current_mood="sad", is_personal_sharing=True,
        )
        tf, tr, tc, tm = _update_tendencies(0.25, 0.25, 0.25, 0.25, signal=signal)
        self.assertGreater(tc, 0.25)

    def test_tendencies_always_sum_to_one(self):
        signal = RelationshipSignalUpdate(
            current_mood="sad", is_personal_sharing=True, is_late_night=True,
            active_topic_category="mood / emotional",
        )
        tf, tr, tc, tm = _update_tendencies(0.25, 0.25, 0.25, 0.25, signal=signal)
        self.assertAlmostEqual(tf + tr + tc + tm, 1.0, places=3)

    def test_tendency_in_full_update(self):
        current = _default_relationship()
        signal = RelationshipSignalUpdate(
            current_mood="sad", active_topic_category="mood / emotional",
            is_personal_sharing=True,
        )
        now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        updates = compute_relationship_update(current, signal=signal, now=now)
        self.assertGreater(updates["tendency_confidant"], 0.25)
        total = (
            updates["tendency_friend"] + updates["tendency_romantic"]
            + updates["tendency_confidant"] + updates["tendency_mentor"]
        )
        self.assertAlmostEqual(total, 1.0, places=3)

    def test_normalize_zero_total_returns_equal(self):
        result = _normalize_tendencies(0, 0, 0, 0)
        self.assertEqual(result, (0.25, 0.25, 0.25, 0.25))

    def test_dominant_tendency_affects_rendering(self):
        rel = _default_relationship(
            intimacy_level=0.5,
            relationship_stage="familiar",
            tendency_friend=0.15,
            tendency_romantic=0.15,
            tendency_confidant=0.55,
            tendency_mentor=0.15,
            total_turns=50,
        )
        profile = _default_profile()
        lines = _render_companion_profile(profile, relationship=rel)
        rendered = "\n".join(lines)
        self.assertIn("倾听", rendered)  # confidant nuance: "多倾听少建议"


# ---- #3: Nickname Frequency ----

class TestNicknameFrequency(unittest.TestCase):
    def test_bump_frequency_on_text_match(self):
        nicknames = [
            {"name": "小襄", "target": "ai", "created_by": "user", "frequency": 3,
             "accepted": True, "context": "", "sentiment": ""},
        ]
        result = _bump_nickname_frequency(nicknames, "小襄，今天过得怎么样？")
        self.assertEqual(result[0]["frequency"], 4)

    def test_no_bump_without_match(self):
        nicknames = [
            {"name": "小襄", "target": "ai", "created_by": "user", "frequency": 3,
             "accepted": True, "context": "", "sentiment": ""},
        ]
        result = _bump_nickname_frequency(nicknames, "今天天气不错")
        self.assertEqual(result[0]["frequency"], 3)

    def test_bump_in_full_update(self):
        current = _default_relationship(
            nicknames=[
                {"name": "晚晚", "target": "ai", "created_by": "user", "frequency": 5,
                 "accepted": True, "context": "", "sentiment": ""},
            ],
        )
        signal = RelationshipSignalUpdate(
            current_mood="happy", user_text="晚晚，来陪我聊天",
        )
        now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        updates = compute_relationship_update(current, signal=signal, now=now)
        self.assertIn("nicknames", updates)
        self.assertEqual(updates["nicknames"][0]["frequency"], 6)


# ---- #4: Mood History with Timestamps ----

class TestTimestampedMoodHistory(unittest.TestCase):
    def test_mood_entry_has_timestamp(self):
        current = _default_relationship()
        signal = RelationshipSignalUpdate(current_mood="anxious")
        now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        updates = compute_relationship_update(current, signal=signal, now=now)

        entry = updates["mood_history"][0]
        self.assertIsInstance(entry, dict)
        self.assertEqual(entry["mood"], "anxious")
        self.assertIn("at", entry)
        self.assertIn("2026-03-17", entry["at"])

    def test_trend_filters_by_24h_window(self):
        now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        # Old moods (>24h ago) are negative, recent moods are positive
        history = [
            _mood_entry("anxious", hours_ago=30, ref=now),
            _mood_entry("stressed", hours_ago=28, ref=now),
            _mood_entry("sad", hours_ago=26, ref=now),
            # Within 24h:
            _mood_entry("calm", hours_ago=6, ref=now),
            _mood_entry("happy", hours_ago=3, ref=now),
            _mood_entry("optimistic", hours_ago=1, ref=now),
        ]
        # With 24h filter: only sees calm, happy, optimistic (all positive) → stable (no earlier to compare)
        # Without filter: would see declining→improving
        trend = _compute_emotional_trend(history, now=now)
        # Only 3 moods in window, no earlier group → stable
        self.assertEqual(trend, "stable")

    def test_trend_with_mixed_window(self):
        now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        history = [
            _mood_entry("happy", hours_ago=20, ref=now),     # in window
            _mood_entry("calm", hours_ago=16, ref=now),      # in window
            _mood_entry("optimistic", hours_ago=12, ref=now),  # in window
            _mood_entry("anxious", hours_ago=6, ref=now),    # in window
            _mood_entry("stressed", hours_ago=3, ref=now),   # in window
            _mood_entry("sad", hours_ago=1, ref=now),        # in window
        ]
        trend = _compute_emotional_trend(history, now=now)
        self.assertEqual(trend, "declining")

    def test_backward_compat_plain_strings(self):
        # Old format (no timestamps) should still work
        history = ["anxious", "anxious", "anxious", "calm", "optimistic", "happy"]
        trend = _compute_emotional_trend(history, now=datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc))
        self.assertEqual(trend, "improving")

    def test_insufficient_recent_moods_returns_empty(self):
        now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        # All moods are >24h old
        history = [
            _mood_entry("happy", hours_ago=30, ref=now),
            _mood_entry("calm", hours_ago=28, ref=now),
            _mood_entry("sad", hours_ago=26, ref=now),
        ]
        trend = _compute_emotional_trend(history, now=now)
        self.assertEqual(trend, "")


# ---- Original tests (kept) ----

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
        now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        result = _maybe_transition_stage("stranger", 0.15, recent.isoformat(), now)
        self.assertIsNone(result)

    def test_cooldown_expired_allows_transition(self):
        old = datetime(2026, 3, 14, 10, 0, tzinfo=timezone.utc)
        now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        result = _maybe_transition_stage("stranger", 0.15, old.isoformat(), now)
        self.assertIsNotNone(result)


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
        rel = _default_relationship(
            intimacy_level=0.5, relationship_stage="familiar",
            tendency_friend=0.4, tendency_romantic=0.2, tendency_confidant=0.2, tendency_mentor=0.2,
            streak_days=5, total_turns=87, avg_session_turns=8.0,
            mood_history=[_mood_entry("calm", 3), _mood_entry("calm", 2), _mood_entry("calm", 1)],
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
        self.assertIsInstance(lines, list)

    def test_stress_high_declining_shows_strategy(self):
        now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        rel = _default_relationship(
            intimacy_level=0.3, relationship_stage="acquaintance",
            streak_days=2, total_turns=20, avg_session_turns=5.0,
            mood_history=[
                _mood_entry("happy", 10, now), _mood_entry("calm", 8, now),
                _mood_entry("anxious", 6, now), _mood_entry("stressed", 3, now),
                _mood_entry("sad", 1, now),
            ],
        )
        profile = _default_profile(
            current_mood="stressed", stress_level="high",
            personal_facts=["他养了一只猫"],
            last_active_at="2026-03-17T10:00:00+00:00", total_interactions=20,
        )
        lines = _render_companion_profile(profile, relationship=rel)
        rendered = "\n".join(lines)
        self.assertIn("declining", rendered)
        self.assertIn("共情", rendered)
        self.assertIn("你记得", rendered)
        self.assertIn("猫", rendered)

    def test_nickname_rendering(self):
        rel = _default_relationship(
            intimacy_level=0.5, relationship_stage="familiar",
            streak_days=3, total_turns=50, avg_session_turns=6.0,
            nicknames=[{"name": "小襄", "target": "ai", "created_by": "user",
                       "frequency": 12, "accepted": True, "context": "", "sentiment": "playful"}],
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
        late = datetime(2026, 3, 17, 15, 30, tzinfo=timezone.utc)
        self.assertTrue(_is_late_night_utc8(late))
        morning = datetime(2026, 3, 17, 2, 0, tzinfo=timezone.utc)
        self.assertFalse(_is_late_night_utc8(morning))

    def test_detect_topic_category_emotional(self):
        self.assertEqual(_detect_active_topic_category("我好焦虑"), "mood / emotional")
        self.assertEqual(_detect_active_topic_category("I feel so stressed"), "mood / emotional")

    def test_detect_topic_category_banter(self):
        self.assertEqual(_detect_active_topic_category("哈哈太搞笑了"), "joke / banter")

    def test_detect_topic_category_work(self):
        self.assertEqual(_detect_active_topic_category("今天公司开会了"), "work / office")

    def test_detect_topic_category_none(self):
        self.assertIsNone(_detect_active_topic_category("嗯"))


if __name__ == "__main__":
    unittest.main()
