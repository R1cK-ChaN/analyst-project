"""Tests for enhanced nickname extraction — English patterns, direct user text detection.

Covers: English personal_facts extraction, direct user message detection,
Chinese user message detection, edge cases, and integration with signal flow.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from analyst.memory.relationship import (
    detect_nickname_from_text,
    extract_nicknames_from_facts,
    compute_relationship_update,
)
from analyst.memory.profile import RelationshipSignalUpdate
from analyst.memory.service import _is_nickname_fact
from analyst.storage import SQLiteEngineStore
from analyst.storage.sqlite_records import CompanionRelationshipStateRecord


def _make_store() -> SQLiteEngineStore:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return SQLiteEngineStore(db_path=Path(tmp.name))


def _default_relationship(client_id: str = "u1", **overrides) -> CompanionRelationshipStateRecord:
    defaults = dict(
        client_id=client_id,
        intimacy_level=0.3,
        relationship_stage="familiar",
        tendency_friend=0.4,
        tendency_romantic=0.2,
        tendency_confidant=0.2,
        tendency_mentor=0.2,
        streak_days=3,
        total_turns=30,
        avg_session_turns=6.0,
        mood_history=[],
        nicknames=[],
        previous_stage="acquaintance",
        last_interaction_date="2026-03-16",
        last_stage_transition_at="2026-03-10T00:00:00+00:00",
        created_at="2026-03-01T00:00:00+00:00",
        updated_at="2026-03-16T00:00:00+00:00",
    )
    defaults.update(overrides)
    return CompanionRelationshipStateRecord(**defaults)


# ---------------------------------------------------------------------------
# English personal_facts extraction
# ---------------------------------------------------------------------------

class TestEnglishFactsExtraction(unittest.TestCase):
    def test_user_calls_me(self):
        facts = ["user calls me Shawn"]
        entries = extract_nicknames_from_facts(facts)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].name, "Shawn")
        self.assertEqual(entries[0].target, "ai")
        self.assertEqual(entries[0].created_by, "user")

    def test_calls_me_with_quotes(self):
        facts = ['user calls me "little one"']
        entries = extract_nicknames_from_facts(facts)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].name, "little one")

    def test_i_call_them(self):
        facts = ["I call them Boss"]
        entries = extract_nicknames_from_facts(facts)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].name, "Boss")
        self.assertEqual(entries[0].target, "user")
        self.assertEqual(entries[0].created_by, "ai")

    def test_i_call_him(self):
        facts = ["I call him big bro"]
        entries = extract_nicknames_from_facts(facts)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].name, "big bro")

    def test_i_call_her(self):
        facts = ["I call her Mei"]
        entries = extract_nicknames_from_facts(facts)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].name, "Mei")

    def test_mixed_chinese_english_facts(self):
        facts = ["用户叫我小襄", "I call them Boss", "he likes cats"]
        entries = extract_nicknames_from_facts(facts)
        self.assertEqual(len(entries), 2)
        names = {e.name for e in entries}
        self.assertIn("小襄", names)
        self.assertIn("Boss", names)

    def test_english_non_nickname_fact_ignored(self):
        facts = ["user is a data scientist", "user lives in Singapore"]
        entries = extract_nicknames_from_facts(facts)
        self.assertEqual(len(entries), 0)


# ---------------------------------------------------------------------------
# Chinese personal_facts: relaxed anchor
# ---------------------------------------------------------------------------

class TestChineseFactsRelaxedAnchor(unittest.TestCase):
    def test_nickname_mid_sentence(self):
        facts = ["用户叫我小襄，我很喜欢这个名字"]
        entries = extract_nicknames_from_facts(facts)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].name, "小襄")

    def test_nickname_with_period(self):
        facts = ["用户叫我宝贝。"]
        entries = extract_nicknames_from_facts(facts)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].name, "宝贝")

    def test_nickname_end_of_line(self):
        """Original end-of-line pattern still works."""
        facts = ["用户叫我小襄"]
        entries = extract_nicknames_from_facts(facts)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].name, "小襄")


# ---------------------------------------------------------------------------
# Direct user text nickname detection
# ---------------------------------------------------------------------------

class TestDetectNicknameFromText(unittest.TestCase):
    # --- Chinese: user naming the AI ---
    def test_cn_call_you(self):
        ai, user = detect_nickname_from_text("以后叫你小襄吧")
        self.assertEqual(ai, "小襄")
        self.assertIsNone(user)

    def test_cn_call_you_simple(self):
        ai, user = detect_nickname_from_text("叫你宝贝了")
        self.assertEqual(ai, "宝贝")

    def test_cn_you_are_our(self):
        ai, user = detect_nickname_from_text("你就是我们的孩子了")
        self.assertEqual(ai, "孩子")

    def test_cn_give_nickname(self):
        ai, user = detect_nickname_from_text("给你取个名字叫阿襄吧")
        self.assertEqual(ai, "阿襄")

    # --- English: user naming the AI ---
    def test_en_call_you(self):
        ai, user = detect_nickname_from_text("I'll call you Shawnie")
        self.assertEqual(ai, "Shawnie")
        self.assertIsNone(user)

    def test_en_from_now_on_call_you(self):
        ai, user = detect_nickname_from_text("from now on, call you buddy")
        self.assertEqual(ai, "buddy")

    def test_en_you_are_our_children(self):
        ai, user = detect_nickname_from_text("from now on, you are our children, shawn")
        # Should capture something (the first match)
        self.assertIsNotNone(ai)

    def test_en_your_name_is(self):
        ai, user = detect_nickname_from_text("your name is Xiao Xiang")
        self.assertEqual(ai, "Xiao Xiang")

    def test_en_nickname_you(self):
        ai, user = detect_nickname_from_text("I'll nickname you Sunny")
        self.assertEqual(ai, "Sunny")

    def test_en_let_me_call_you(self):
        ai, user = detect_nickname_from_text("let me call you kiddo")
        self.assertEqual(ai, "kiddo")

    # --- Chinese: user naming themselves ---
    def test_cn_call_me(self):
        ai, user = detect_nickname_from_text("以后叫我哥哥吧")
        self.assertIsNone(ai)
        self.assertEqual(user, "哥哥")

    def test_cn_call_me_simple(self):
        ai, user = detect_nickname_from_text("叫我老板")
        self.assertEqual(user, "老板")

    # --- English: user naming themselves ---
    def test_en_call_me(self):
        ai, user = detect_nickname_from_text("call me Alex")
        self.assertIsNone(ai)
        self.assertEqual(user, "Alex")

    def test_en_my_name_is(self):
        ai, user = detect_nickname_from_text("my name is Rick")
        self.assertEqual(user, "Rick")

    # --- No match ---
    def test_no_match_normal_text(self):
        ai, user = detect_nickname_from_text("今天天气不错")
        self.assertIsNone(ai)
        self.assertIsNone(user)

    def test_no_match_english_normal(self):
        ai, user = detect_nickname_from_text("hello how are you")
        self.assertIsNone(ai)
        self.assertIsNone(user)

    def test_empty_text(self):
        ai, user = detect_nickname_from_text("")
        self.assertIsNone(ai)
        self.assertIsNone(user)

    # --- Edge cases ---
    def test_too_long_nickname_filtered(self):
        ai, user = detect_nickname_from_text("call you " + "x" * 30)
        self.assertIsNone(ai)  # Over 20 chars, filtered out

    def test_both_directions(self):
        """User assigns both directions in one message."""
        ai, user = detect_nickname_from_text("叫你小襄吧，叫我老大")
        self.assertEqual(ai, "小襄")
        self.assertEqual(user, "老大")


# ---------------------------------------------------------------------------
# _is_nickname_fact: English support
# ---------------------------------------------------------------------------

class TestIsNicknameFact(unittest.TestCase):
    def test_chinese_nickname_fact(self):
        self.assertTrue(_is_nickname_fact("用户叫我小襄"))
        self.assertTrue(_is_nickname_fact("我叫他哥哥"))

    def test_english_nickname_fact(self):
        self.assertTrue(_is_nickname_fact("user calls me Shawn"))
        self.assertTrue(_is_nickname_fact("I call them Boss"))
        self.assertTrue(_is_nickname_fact("he calls me buddy"))

    def test_non_nickname_fact(self):
        self.assertFalse(_is_nickname_fact("he likes cats"))
        self.assertFalse(_is_nickname_fact("user is a data scientist"))


# ---------------------------------------------------------------------------
# Signal integration: nickname_for_ai / nickname_for_user populated
# ---------------------------------------------------------------------------

class TestSignalIntegration(unittest.TestCase):
    def test_signal_updates_nickname_list(self):
        current = _default_relationship(nicknames=[])
        signal = RelationshipSignalUpdate(
            nickname_for_ai="小襄",
            user_text="叫你小襄吧",
        )
        now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        updates = compute_relationship_update(current, signal=signal, now=now)
        self.assertIn("nicknames", updates)
        ai_nicks = [n for n in updates["nicknames"] if n.get("target") == "ai"]
        self.assertEqual(len(ai_nicks), 1)
        self.assertEqual(ai_nicks[0]["name"], "小襄")

    def test_signal_updates_user_nickname(self):
        current = _default_relationship(nicknames=[])
        signal = RelationshipSignalUpdate(
            nickname_for_user="Boss",
            user_text="call me Boss",
        )
        now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        updates = compute_relationship_update(current, signal=signal, now=now)
        self.assertIn("nicknames", updates)
        user_nicks = [n for n in updates["nicknames"] if n.get("target") == "user"]
        self.assertEqual(len(user_nicks), 1)
        self.assertEqual(user_nicks[0]["name"], "Boss")

    def test_duplicate_nickname_increments_frequency(self):
        current = _default_relationship(
            nicknames=[{"name": "小襄", "target": "ai", "created_by": "user",
                       "frequency": 3, "accepted": True, "context": "", "sentiment": ""}],
        )
        signal = RelationshipSignalUpdate(
            nickname_for_ai="小襄",
            user_text="小襄",
        )
        now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        updates = compute_relationship_update(current, signal=signal, now=now)
        self.assertIn("nicknames", updates)
        ai_nicks = [n for n in updates["nicknames"] if n.get("target") == "ai"]
        # +1 from _update_nicknames (signal match) + +1 from _bump_nickname_frequency (text mention)
        self.assertEqual(ai_nicks[0]["frequency"], 5)

    def test_no_nickname_signal_leaves_list_unchanged(self):
        current = _default_relationship(nicknames=[])
        signal = RelationshipSignalUpdate(
            current_mood="calm",
            user_text="今天天气不错",
        )
        now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        updates = compute_relationship_update(current, signal=signal, now=now)
        self.assertNotIn("nicknames", updates)


# ---------------------------------------------------------------------------
# End-to-end: store round-trip with English nickname
# ---------------------------------------------------------------------------

class TestStoreRoundTrip(unittest.TestCase):
    def test_english_nickname_stored_and_retrieved(self):
        store = _make_store()
        nicknames = [
            {"name": "Shawn", "target": "ai", "created_by": "user",
             "frequency": 1, "accepted": True, "context": "", "sentiment": "casual"},
        ]
        store.update_companion_relationship_state(client_id="u1", nicknames=nicknames)
        rel = store.get_companion_relationship_state(client_id="u1")
        self.assertEqual(len(rel.nicknames), 1)
        self.assertEqual(rel.nicknames[0]["name"], "Shawn")


if __name__ == "__main__":
    unittest.main()
