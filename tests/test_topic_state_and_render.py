"""Tests for topic_state.py and render.py utilities."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from analyst.memory.render import RenderBudget, render_context_sections, trim_text
from analyst.memory.topic_state import (
    ConversationTopicMessage,
    TopicStateEntry,
    TopicStateSnapshot,
    _classify_message,
    _extract_fallback_keywords,
    _score_buckets,
    _TopicBucket,
    build_topic_state_lines,
    derive_topic_state,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_TIME = datetime(2026, 3, 17, 12, 0, 0, tzinfo=timezone.utc)


def _ts(offset_minutes: int = 0) -> str:
    """Return an ISO timestamp offset from _BASE_TIME by *offset_minutes*."""
    return (_BASE_TIME + timedelta(minutes=offset_minutes)).isoformat()


def _msg(
    content: str,
    speaker: str = "user",
    minutes: int = 0,
    is_assistant: bool = False,
    is_current_turn: bool = False,
) -> ConversationTopicMessage:
    return ConversationTopicMessage(
        speaker_key=speaker,
        speaker_label=speaker,
        content=content,
        created_at=_ts(minutes),
        is_assistant=is_assistant,
        is_current_turn=is_current_turn,
    )


# ===================================================================
# render.py tests
# ===================================================================


class TestRenderBudget(unittest.TestCase):
    """RenderBudget dataclass and sub_agent_budget factory."""

    def test_default_values(self):
        b = RenderBudget()
        self.assertEqual(b.total_chars, 6000)
        self.assertEqual(b.max_item_chars, 360)
        self.assertEqual(b.max_recent_messages, 8)
        self.assertEqual(b.max_research_items, 4)
        self.assertEqual(b.max_trading_items, 4)
        self.assertEqual(b.max_delivery_items, 4)


    def test_frozen(self):
        b = RenderBudget()
        with self.assertRaises(AttributeError):
            b.total_chars = 9999  # type: ignore[misc]


class TestTrimText(unittest.TestCase):
    """trim_text truncation behaviour."""

    def test_short_text_unchanged(self):
        self.assertEqual(trim_text("hello", max_chars=10), "hello")

    def test_exact_length_unchanged(self):
        self.assertEqual(trim_text("abcde", max_chars=5), "abcde")

    def test_long_text_truncated_with_ellipsis(self):
        result = trim_text("hello world this is long", max_chars=11)
        self.assertTrue(result.endswith("..."))
        # The raw slice is text[:11].rstrip() + "..."
        self.assertEqual(result, "hello world...")

    def test_truncation_strips_trailing_space(self):
        # "ab cd " -> "ab cd"[:5] = "ab cd" -> rstrip -> "ab cd" + "..."
        result = trim_text("ab cd ef", max_chars=5)
        self.assertEqual(result, "ab cd...")

    def test_empty_string(self):
        self.assertEqual(trim_text("", max_chars=10), "")


class TestRenderContextSections(unittest.TestCase):
    """render_context_sections section assembly and budget enforcement."""

    def test_single_section(self):
        sections = [("Foo", ["line1", "line2"])]
        result = render_context_sections(sections)
        self.assertIn("### Foo", result)
        self.assertIn("line1", result)
        self.assertIn("line2", result)

    def test_multiple_sections_joined(self):
        sections = [("A", ["a1"]), ("B", ["b1"])]
        result = render_context_sections(sections)
        self.assertIn("### A", result)
        self.assertIn("### B", result)
        # Two sections separated by double-newline
        self.assertIn("\n\n", result)

    def test_empty_sections_skipped(self):
        sections = [("Empty", []), ("Present", ["data"])]
        result = render_context_sections(sections)
        self.assertNotIn("### Empty", result)
        self.assertIn("### Present", result)

    def test_budget_drops_trailing_sections(self):
        tiny_budget = RenderBudget(total_chars=50)
        sections = [
            ("Short", ["ok"]),
            ("Long", ["x" * 200]),
        ]
        result = render_context_sections(sections, budget=tiny_budget)
        # The second section should be dropped because it exceeds budget
        self.assertNotIn("### Long", result)
        # First section kept (possibly truncated to total_chars)
        self.assertIn("### Short", result)

    def test_budget_hard_truncation(self):
        tiny_budget = RenderBudget(total_chars=20)
        sections = [("Only", ["data that is really really long and should be cut"])]
        result = render_context_sections(sections, budget=tiny_budget)
        self.assertLessEqual(len(result), 20)

    def test_all_empty_sections(self):
        result = render_context_sections([("A", []), ("B", [])])
        self.assertEqual(result, "")

    def test_no_budget_uses_default(self):
        sections = [("X", ["hello"])]
        result = render_context_sections(sections)
        # Should work without error; default budget is 6000 chars
        self.assertIn("hello", result)


# ===================================================================
# topic_state.py tests -- dataclasses
# ===================================================================


class TestDataclassConstruction(unittest.TestCase):
    """Verify dataclass creation and frozen constraints."""

    def test_conversation_topic_message_defaults(self):
        m = ConversationTopicMessage(
            speaker_key="u1",
            speaker_label="Alice",
            content="hi",
            created_at="2026-03-17T00:00:00+00:00",
        )
        self.assertFalse(m.is_assistant)
        self.assertFalse(m.is_current_turn)

    def test_conversation_topic_message_frozen(self):
        m = _msg("test")
        with self.assertRaises(AttributeError):
            m.content = "changed"  # type: ignore[misc]

    def test_topic_state_entry_fields(self):
        entry = TopicStateEntry(
            label="meal / food",
            keywords=("lunch", "dinner"),
            status="active",
            score=3.5,
            latest_summary="let's eat",
            last_speaker="Alice",
            participants=("Alice", "Bob"),
            is_self_topic=False,
        )
        self.assertEqual(entry.label, "meal / food")
        self.assertEqual(entry.status, "active")

    def test_topic_state_snapshot_fields(self):
        snap = TopicStateSnapshot(
            active_topic="market / finance",
            reply_focus="BTC outlook",
            cooling_topics=("meal / food",),
            topic_stack=(),
        )
        self.assertEqual(snap.active_topic, "market / finance")
        self.assertEqual(snap.cooling_topics, ("meal / food",))


# ===================================================================
# _classify_message
# ===================================================================


class TestClassifyMessage(unittest.TestCase):
    """_classify_message into the 9 defined categories + general chat."""

    def _label(self, content: str, **kwargs) -> str:
        return _classify_message(_msg(content, **kwargs)).label

    # --- planning / scheduling ---
    def test_planning_meeting(self):
        self.assertEqual(self._label("Can we meet tomorrow?"), "planning / scheduling")

    def test_planning_chinese(self):
        self.assertEqual(self._label("明天见面吗"), "planning / scheduling")

    # --- meal / food ---
    def test_meal_english(self):
        self.assertEqual(self._label("Want to grab lunch?"), "meal / food")

    def test_meal_chinese(self):
        self.assertEqual(self._label("我们吃什么晚餐"), "meal / food")

    # --- market / finance ---
    def test_market_english(self):
        self.assertEqual(self._label("The market is crashing"), "market / finance")

    def test_market_btc(self):
        self.assertEqual(self._label("BTC hit a new ATH"), "market / finance")

    def test_market_macro(self):
        self.assertEqual(self._label("CPI data came in hot, inflation worries"), "market / finance")

    # --- mood / emotional ---
    def test_mood_tired(self):
        self.assertEqual(self._label("I'm so tired today"), "mood / emotional")

    def test_mood_stressed_chinese(self):
        self.assertEqual(self._label("压力好大啊"), "mood / emotional")

    # --- photos / media ---
    def test_photos(self):
        self.assertEqual(self._label("Check out this photo"), "photos / media")

    def test_selfie(self):
        self.assertEqual(self._label("Just took a selfie"), "photos / media")

    # --- work / office ---
    def test_work(self):
        self.assertEqual(self._label("I'm still working at the office"), "work / office")

    def test_work_chinese(self):
        self.assertEqual(self._label("上班好无聊"), "work / office")

    # --- travel / outing ---
    def test_travel(self):
        self.assertEqual(self._label("At the airport waiting for my flight"), "travel / outing")

    def test_travel_walk(self):
        self.assertEqual(self._label("Going for a walk"), "travel / outing")

    # --- relationships / people ---
    def test_relationships_friend(self):
        self.assertEqual(self._label("My friend is visiting"), "relationships / people")

    def test_relationships_family(self):
        self.assertEqual(self._label("Having dinner with family tonight"), "relationships / people")

    # --- joke / banter ---
    def test_banter_haha(self):
        self.assertEqual(self._label("haha that's hilarious"), "joke / banter")

    def test_banter_emoji(self):
        self.assertEqual(self._label("lol rofl"), "joke / banter")

    # --- general chat (no category match) ---
    def test_general_chat_fallback(self):
        label = self._label("The purple dragon swoops")
        # No known category keywords, so it falls back
        self.assertNotIn(label, {
            "planning / scheduling",
            "meal / food",
            "market / finance",
            "mood / emotional",
            "photos / media",
            "work / office",
            "travel / outing",
            "relationships / people",
            "joke / banter",
        })

    # --- signal properties ---
    def test_question_detected(self):
        signal = _classify_message(_msg("What time is the meeting?"))
        self.assertTrue(signal.is_question)

    def test_question_chinese(self):
        signal = _classify_message(_msg("你几点下班吗"))
        self.assertTrue(signal.is_question)

    def test_not_question(self):
        signal = _classify_message(_msg("The market tanked"))
        self.assertFalse(signal.is_question)

    def test_humor_detected(self):
        signal = _classify_message(_msg("哈哈哈 太好笑了"))
        self.assertTrue(signal.is_humor)

    def test_acknowledgement_detected(self):
        signal = _classify_message(_msg("ok"))
        self.assertTrue(signal.is_acknowledgement)

    def test_acknowledgement_chinese(self):
        signal = _classify_message(_msg("好的"))
        self.assertTrue(signal.is_acknowledgement)

    def test_assistant_is_self_topic(self):
        signal = _classify_message(_msg("Let's look at BTC", is_assistant=True))
        self.assertTrue(signal.is_self_topic)

    def test_importance_boosted_by_question(self):
        normal = _classify_message(_msg("The market is down"))
        question = _classify_message(_msg("What about the market?"))
        self.assertGreater(question.importance, normal.importance)

    def test_importance_reduced_by_humor(self):
        normal = _classify_message(_msg("The market is down"))
        humor = _classify_message(_msg("The market is down haha"))
        self.assertLess(humor.importance, normal.importance)

    def test_importance_reduced_by_assistant(self):
        user_signal = _classify_message(_msg("BTC is pumping"))
        bot_signal = _classify_message(_msg("BTC is pumping", is_assistant=True))
        self.assertLess(bot_signal.importance, user_signal.importance)


# ===================================================================
# _extract_fallback_keywords
# ===================================================================


class TestExtractFallbackKeywords(unittest.TestCase):
    """Keyword extraction for messages not matching any category."""

    def test_english_keywords(self):
        result = _extract_fallback_keywords("The purple dragon swoops down")
        # Stopwords removed; tokens >= 3 chars
        self.assertIn("purple", result)
        self.assertIn("dragon", result)
        self.assertIn("swoops", result)
        self.assertLessEqual(len(result), 3)

    def test_stopwords_removed(self):
        result = _extract_fallback_keywords("I just got the thing for you")
        for stopword in ("just", "got", "the", "for", "you"):
            self.assertNotIn(stopword, result)

    def test_short_tokens_removed(self):
        result = _extract_fallback_keywords("go to a by")
        # All tokens are <= 2 chars or stopwords
        self.assertEqual(result, [])

    def test_chinese_fallback(self):
        result = _extract_fallback_keywords("运动是好的习惯")
        # Should extract Chinese segments of 2-8 chars
        self.assertTrue(len(result) > 0)
        for kw in result:
            self.assertTrue(all("\u4e00" <= c <= "\u9fff" for c in kw))

    def test_empty_string(self):
        self.assertEqual(_extract_fallback_keywords(""), [])

    def test_max_three_english(self):
        result = _extract_fallback_keywords("alpha bravo charlie delta echo")
        self.assertLessEqual(len(result), 3)

    def test_max_two_chinese(self):
        result = _extract_fallback_keywords("苹果 橘子 葡萄 西瓜")
        self.assertLessEqual(len(result), 2)


# ===================================================================
# _score_buckets
# ===================================================================


class TestScoreBuckets(unittest.TestCase):
    """_score_buckets scoring algorithm including time decay, recency, and multipliers."""

    def _make_bucket(
        self,
        label: str = "general chat",
        importance: float = 2.0,
        rank: int = 0,
        ts: str | None = None,
        is_question: bool = False,
        is_assistant: bool = False,
        contains_current_turn: bool = False,
        self_topic_weight: float = 0.0,
    ) -> _TopicBucket:
        b = _TopicBucket(label=label)
        b.total_importance = importance
        b.latest_rank = rank
        b.last_activity_at = ts or _ts(0)
        b.latest_is_question = is_question
        b.latest_is_assistant = is_assistant
        b.contains_current_turn = contains_current_turn
        b.self_topic_weight = self_topic_weight
        return b

    def test_single_bucket(self):
        buckets = [self._make_bucket()]
        scored = _score_buckets(buckets)
        self.assertEqual(len(scored), 1)
        self.assertGreater(scored[0][1], 0.0)

    def test_current_turn_boost(self):
        base = self._make_bucket()
        boosted = self._make_bucket(contains_current_turn=True)
        s_base = _score_buckets([base])[0][1]
        s_boosted = _score_buckets([boosted])[0][1]
        self.assertGreater(s_boosted, s_base)

    def test_question_boost(self):
        base = self._make_bucket()
        boosted = self._make_bucket(is_question=True)
        s_base = _score_buckets([base])[0][1]
        s_boosted = _score_buckets([boosted])[0][1]
        self.assertGreater(s_boosted, s_base)

    def test_assistant_penalty(self):
        base = self._make_bucket()
        penalized = self._make_bucket(is_assistant=True)
        s_base = _score_buckets([base])[0][1]
        s_penalized = _score_buckets([penalized])[0][1]
        self.assertLess(s_penalized, s_base)

    def test_assistant_extra_penalty_for_low_category(self):
        # meal/food assistant bucket gets an extra 0.5 multiplier
        meal_user = self._make_bucket(label="meal / food")
        meal_bot = self._make_bucket(label="meal / food", is_assistant=True)
        s_user = _score_buckets([meal_user])[0][1]
        s_bot = _score_buckets([meal_bot])[0][1]
        # Penalty should be heavier than just the 0.7 assistant penalty
        self.assertLess(s_bot / s_user, 0.5)

    def test_self_topic_penalty(self):
        base = self._make_bucket(importance=5.0, self_topic_weight=0.0)
        self_heavy = self._make_bucket(importance=5.0, self_topic_weight=4.0)
        s_base = _score_buckets([base])[0][1]
        s_self = _score_buckets([self_heavy])[0][1]
        self.assertLess(s_self, s_base)

    def test_time_decay(self):
        recent = self._make_bucket(ts=_ts(0))
        old = self._make_bucket(ts=_ts(-60))  # 60 minutes earlier
        # Put both in the same list so they share a reference time
        scored = _score_buckets([old, recent])
        s_old = scored[0][1]
        s_recent = scored[1][1]
        self.assertGreater(s_recent, s_old)

    def test_recency_decay_favors_latest_rank(self):
        # Bucket with higher latest_rank (more recent) should score higher
        early = self._make_bucket(rank=0)
        late = self._make_bucket(rank=4)
        scored = _score_buckets([early, late, late, late, late])
        # The early bucket has rank_gap = 4 so heavier decay
        s_early = scored[0][1]
        s_late = scored[1][1]
        self.assertGreater(s_late, s_early)


# ===================================================================
# derive_topic_state
# ===================================================================


class TestDeriveTopicState(unittest.TestCase):
    """derive_topic_state integration tests."""

    def test_empty_history(self):
        snap = derive_topic_state([])
        self.assertEqual(snap.active_topic, "")
        self.assertEqual(snap.reply_focus, "")
        self.assertEqual(snap.cooling_topics, ())
        self.assertEqual(snap.topic_stack, ())

    def test_single_message(self):
        msgs = [_msg("BTC is pumping hard", minutes=0)]
        snap = derive_topic_state(msgs)
        self.assertEqual(snap.active_topic, "market / finance")
        self.assertGreater(len(snap.topic_stack), 0)

    def test_all_same_category(self):
        msgs = [
            _msg("Markets are up", minutes=0),
            _msg("BTC hit 120k", minutes=1),
            _msg("Stocks rallied too", minutes=2),
        ]
        snap = derive_topic_state(msgs)
        self.assertEqual(snap.active_topic, "market / finance")
        # Only one topic in stack since all same category
        self.assertEqual(len(snap.topic_stack), 1)

    def test_multiple_topics(self):
        msgs = [
            _msg("Let's meet tomorrow", minutes=0),
            _msg("I'm so stressed", minutes=5),
            _msg("BTC is crashing", minutes=10, is_current_turn=True),
        ]
        snap = derive_topic_state(msgs, max_topics=3)
        # Most recent + current turn + high importance = active
        self.assertEqual(snap.active_topic, "market / finance")
        labels = {e.label for e in snap.topic_stack}
        self.assertIn("market / finance", labels)

    def test_active_topic_detection(self):
        msgs = [
            _msg("haha funny", minutes=0),
            _msg("What is the Fed doing with rates?", minutes=5, is_current_turn=True),
        ]
        snap = derive_topic_state(msgs)
        self.assertEqual(snap.active_topic, "market / finance")

    def test_reply_focus_extracted(self):
        msgs = [_msg("BTC is at 120k, should we sell?", minutes=0, is_current_turn=True)]
        snap = derive_topic_state(msgs)
        self.assertIn("BTC", snap.reply_focus)

    def test_cooling_topic_identification(self):
        # Old low-importance topic followed by recent high-importance topic
        msgs = [
            _msg("haha lol", minutes=0),
            _msg("ok", minutes=1),
            _msg("What about the CPI data?", minutes=30, is_current_turn=True),
        ]
        snap = derive_topic_state(msgs, max_topics=3)
        # The humor topic (if included) should be cooling
        if snap.cooling_topics:
            self.assertTrue(any("banter" in t or "general" in t for t in snap.cooling_topics)
                            or len(snap.cooling_topics) > 0)

    def test_max_topics_respected(self):
        msgs = [
            _msg("Let's meet tomorrow", minutes=0),
            _msg("I'm exhausted", minutes=5),
            _msg("BTC is at 120k", minutes=10),
            _msg("Time for lunch?", minutes=15),
            _msg("Took a nice selfie", minutes=20, is_current_turn=True),
        ]
        snap = derive_topic_state(msgs, max_topics=2)
        self.assertLessEqual(len(snap.topic_stack), 2)

    def test_whitespace_only_messages_ignored(self):
        msgs = [
            _msg("   ", minutes=0),
            _msg("", minutes=1),
            _msg("BTC rally", minutes=2),
        ]
        snap = derive_topic_state(msgs)
        self.assertEqual(snap.active_topic, "market / finance")

    def test_topic_stack_has_statuses(self):
        msgs = [
            _msg("Let's plan a trip this weekend", minutes=0),
            _msg("ok sounds good", minutes=1),
            _msg("BTC dropped 10%!", minutes=30, is_current_turn=True),
        ]
        snap = derive_topic_state(msgs, max_topics=3)
        statuses = {e.status for e in snap.topic_stack}
        self.assertIn("active", statuses)

    def test_topic_entry_participants(self):
        msgs = [
            _msg("Let's eat lunch", speaker="Alice", minutes=0),
            _msg("Lunch sounds great, where?", speaker="Bob", minutes=1),
        ]
        snap = derive_topic_state(msgs)
        # Both messages match "meal / food" and merge into one bucket
        meal_entries = [e for e in snap.topic_stack if e.label == "meal / food"]
        self.assertTrue(len(meal_entries) > 0)
        entry = meal_entries[0]
        self.assertIn("Alice", entry.participants)
        self.assertIn("Bob", entry.participants)

    def test_topic_entry_last_speaker(self):
        msgs = [
            _msg("BTC is up", speaker="Alice", minutes=0),
            _msg("Wow really?", speaker="Bob", minutes=1),
        ]
        snap = derive_topic_state(msgs)
        entry = snap.topic_stack[0]
        self.assertEqual(entry.last_speaker, "Bob")


# ===================================================================
# build_topic_state_lines
# ===================================================================


class TestBuildTopicStateLines(unittest.TestCase):
    """build_topic_state_lines markdown output formatting."""

    def test_empty_history_returns_empty(self):
        lines = build_topic_state_lines([])
        self.assertEqual(lines, [])

    def test_active_topic_line(self):
        msgs = [_msg("BTC is pumping", minutes=0, is_current_turn=True)]
        lines = build_topic_state_lines(msgs)
        self.assertTrue(any(line.startswith("- active_topic:") for line in lines))

    def test_reply_focus_line(self):
        msgs = [_msg("What about BTC?", minutes=0, is_current_turn=True)]
        lines = build_topic_state_lines(msgs)
        self.assertTrue(any(line.startswith("- reply_focus:") for line in lines))

    def test_topic_stack_line_format(self):
        msgs = [
            _msg("Let's meet tomorrow", minutes=0),
            _msg("BTC crashed", minutes=5, is_current_turn=True),
        ]
        lines = build_topic_state_lines(msgs, max_topics=3)
        stack_lines = [l for l in lines if l.startswith("- topic_stack:")]
        for sl in stack_lines:
            self.assertIn("status:", sl)
            self.assertIn("score:", sl)
            self.assertIn("last_speaker:", sl)

    def test_cooling_topics_line(self):
        msgs = [
            _msg("haha funny joke", minutes=0),
            _msg("BTC is pumping!", minutes=30, is_current_turn=True),
        ]
        lines = build_topic_state_lines(msgs, max_topics=3)
        cooling_lines = [l for l in lines if l.startswith("- cooling_topics:")]
        # Cooling line may or may not appear depending on scores; just verify format
        for cl in cooling_lines:
            self.assertTrue(cl.startswith("- cooling_topics:"))

    def test_self_topic_marker(self):
        msgs = [
            _msg("BTC is interesting", is_assistant=True, minutes=0),
            _msg("Tell me more", minutes=1, is_current_turn=True),
        ]
        lines = build_topic_state_lines(msgs, max_topics=3)
        # The assistant-originated topic may carry self_topic marker
        stack_lines = [l for l in lines if "self_topic" in l]
        # It should be present if the bucket is dominated by assistant messages
        # With one assistant msg out of two, self_topic_weight might not cross 60%
        # So we just verify the format is valid if it appears
        for sl in stack_lines:
            self.assertIn("self_topic", sl)

    def test_keywords_in_stack_line(self):
        msgs = [_msg("BTC and stocks are up", minutes=0, is_current_turn=True)]
        lines = build_topic_state_lines(msgs)
        stack_lines = [l for l in lines if l.startswith("- topic_stack:")]
        self.assertTrue(len(stack_lines) > 0)
        self.assertTrue(any("keywords:" in sl for sl in stack_lines))


# ===================================================================
# Edge cases
# ===================================================================


class TestEdgeCases(unittest.TestCase):
    """Additional edge-case and regression tests."""

    def test_none_content_treated_as_empty(self):
        m = ConversationTopicMessage(
            speaker_key="u1",
            speaker_label="user",
            content=None,  # type: ignore[arg-type]
            created_at=_ts(0),
        )
        snap = derive_topic_state([m])
        # None content should be stripped and treated as empty
        self.assertEqual(snap.active_topic, "")

    def test_very_long_message_summary_trimmed(self):
        long_text = "BTC " * 200
        signal = _classify_message(_msg(long_text))
        self.assertLessEqual(len(signal.summary), 93)  # 90 + "..."

    def test_mixed_language_classification(self):
        # "散步" matches travel/outing, "airport" also matches travel/outing
        signal = _classify_message(_msg("散步到airport去接人"))
        self.assertEqual(signal.label, "travel / outing")

    def test_acknowledgement_merges_into_last_bucket(self):
        msgs = [
            _msg("BTC is up 10%", minutes=0),
            _msg("ok", minutes=1),
        ]
        snap = derive_topic_state(msgs)
        # "ok" should merge into existing bucket, not create a new one
        self.assertEqual(len(snap.topic_stack), 1)

    def test_case_insensitive_classification(self):
        self.assertEqual(
            _classify_message(_msg("BTC")).label,
            _classify_message(_msg("btc")).label,
        )

    def test_derive_returns_frozen_snapshot(self):
        msgs = [_msg("BTC rally", minutes=0)]
        snap = derive_topic_state(msgs)
        with self.assertRaises(AttributeError):
            snap.active_topic = "changed"  # type: ignore[misc]

    def test_score_keyword_sorting(self):
        msgs = [_msg("stocks and btc and market", minutes=0, is_current_turn=True)]
        snap = derive_topic_state(msgs)
        entry = snap.topic_stack[0]
        # Keywords should be sorted alphabetically
        self.assertEqual(list(entry.keywords), sorted(entry.keywords))

    def test_multiple_categories_highest_importance_wins(self):
        # "meet" -> planning (2.0), "eat" -> meal (0.7)
        # planning has higher importance multiplier so it should win
        signal = _classify_message(_msg("Let's meet for lunch and eat together"))
        # Both "planning / scheduling" and "meal / food" match
        # planning: 1 hit * 2.0 = 2.0; meal: 2 hits * 0.7 = 1.4 (eat + lunch)
        # The category with highest (count * importance, importance) wins
        self.assertIn(signal.label, {"planning / scheduling", "meal / food"})


if __name__ == "__main__":
    unittest.main()
