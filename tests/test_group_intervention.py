"""Tests for group chat autonomous intervention scoring engine."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from analyst.delivery.group_intervention import (
    BOT_DISPLAY_NAMES,
    BOT_USER_ID,
    INTERVENTION_THRESHOLD,
    MAX_INTEREST_TRIGGERS_PER_DAY,
    InterventionResult,
    InterventionTrigger,
    _check_emotional_gap,
    _check_interest_match,
    _check_name_mention,
    _check_unanswered_question,
    _compute_penalties,
    evaluate_group_intervention,
    should_cancel_intervention,
)

SGT = timezone(timedelta(hours=8))


def _now() -> datetime:
    return datetime(2026, 3, 17, 14, 0, 0, tzinfo=SGT)


def _msg(
    content: str = "",
    user_id: str = "user1",
    display_name: str = "Alice",
    message_id: int = 1,
    minutes_ago: float = 0,
    now: datetime | None = None,
) -> dict:
    base = now or _now()
    created = (base - timedelta(minutes=minutes_ago)).isoformat()
    return {
        "content": content,
        "user_id": user_id,
        "display_name": display_name,
        "message_id": message_id,
        "created_at": created,
    }


# ============================================================
# Trigger detection — name mention
# ============================================================

class TestNameMention:
    def test_exact_chinese_name(self):
        msg = _msg("陈襄你觉得呢")
        assert _check_name_mention(msg, BOT_DISPLAY_NAMES) is not None

    def test_english_name(self):
        msg = _msg("hey Shawn what do you think?")
        assert _check_name_mention(msg, BOT_DISPLAY_NAMES) is not None

    def test_full_english_name(self):
        msg = _msg("Shawn Chan would know")
        assert _check_name_mention(msg, BOT_DISPLAY_NAMES) is not None

    def test_no_mention(self):
        msg = _msg("anyone wanna grab lunch?")
        assert _check_name_mention(msg, BOT_DISPLAY_NAMES) is None

    def test_case_insensitive_english(self):
        msg = _msg("SHAWN do you agree?")
        assert _check_name_mention(msg, BOT_DISPLAY_NAMES) is not None

    def test_returns_correct_score(self):
        msg = _msg("陈襄帮我看看")
        trigger = _check_name_mention(msg, BOT_DISPLAY_NAMES)
        assert trigger is not None
        assert trigger.score == 0.7
        assert trigger.kind == "name_mention"

    def test_delay_range(self):
        msg = _msg("Shawn来一下")
        trigger = _check_name_mention(msg, BOT_DISPLAY_NAMES)
        assert trigger is not None
        assert trigger.delay_range == (30, 60)


# ============================================================
# Trigger detection — interest match
# ============================================================

class TestInterestMatch:
    def test_keyword_match_chinese(self):
        msg = _msg("今天的拿铁真好喝")
        trigger = _check_interest_match(msg, "companion", 0)
        assert trigger is not None
        assert trigger.kind == "interest_match"

    def test_keyword_match_english(self):
        msg = _msg("just got back from the gym")
        trigger = _check_interest_match(msg, "companion", 0)
        assert trigger is not None

    def test_no_keyword(self):
        msg = _msg("talking about finance stuff")
        assert _check_interest_match(msg, "companion", 0) is None

    def test_respects_daily_cap(self):
        msg = _msg("coffee time!")
        assert _check_interest_match(msg, "companion", MAX_INTEREST_TRIGGERS_PER_DAY) is None

    def test_under_daily_cap(self):
        msg = _msg("coffee time!")
        assert _check_interest_match(msg, "companion", MAX_INTEREST_TRIGGERS_PER_DAY - 1) is not None

    def test_unknown_persona_returns_none(self):
        msg = _msg("coffee time!")
        assert _check_interest_match(msg, "unknown_mode", 0) is None

    def test_score_and_delay(self):
        msg = _msg("love jazz music")
        trigger = _check_interest_match(msg, "companion", 0)
        assert trigger is not None
        assert trigger.score == 0.4
        assert trigger.delay_range == (60, 180)

    def test_case_insensitive(self):
        msg = _msg("COFFEE is life")
        assert _check_interest_match(msg, "companion", 0) is not None


# ============================================================
# Trigger detection — unanswered question
# ============================================================

class TestUnansweredQuestion:
    def test_old_question_no_reply(self):
        now = _now()
        msgs = [
            _msg("有人知道怎么办吗？", user_id="user1", message_id=10, minutes_ago=5, now=now),
        ]
        trigger, msg_id = _check_unanswered_question(msgs, msgs[-1], BOT_USER_ID, now)
        assert trigger is not None
        assert trigger.kind == "unanswered_question"
        assert msg_id == 10

    def test_recent_question_ignored(self):
        now = _now()
        msgs = [
            _msg("有人知道吗？", user_id="user1", message_id=10, minutes_ago=1, now=now),
        ]
        trigger, _ = _check_unanswered_question(msgs, msgs[-1], BOT_USER_ID, now)
        assert trigger is None

    def test_question_with_reply_ignored(self):
        now = _now()
        msgs = [
            _msg("有人知道吗？", user_id="user1", message_id=10, minutes_ago=5, now=now),
            _msg("我知道！", user_id="user2", message_id=11, minutes_ago=4, now=now),
        ]
        trigger, _ = _check_unanswered_question(msgs, msgs[-1], BOT_USER_ID, now)
        assert trigger is None

    def test_bot_question_ignored(self):
        now = _now()
        msgs = [
            _msg("你们觉得呢？", user_id=BOT_USER_ID, message_id=10, minutes_ago=5, now=now),
        ]
        trigger, _ = _check_unanswered_question(msgs, msgs[-1], BOT_USER_ID, now)
        assert trigger is None


# ============================================================
# Trigger detection — emotional gap
# ============================================================

class TestEmotionalGap:
    def test_distress_no_support(self):
        now = _now()
        msgs = [
            _msg("崩溃了 受不了了", user_id="user1", message_id=10, minutes_ago=5, now=now),
        ]
        trigger, msg_id = _check_emotional_gap(msgs, msgs[-1], BOT_USER_ID, now)
        assert trigger is not None
        assert trigger.kind == "emotional_gap"
        assert msg_id == 10

    def test_distress_with_support_ignored(self):
        now = _now()
        msgs = [
            _msg("好痛苦", user_id="user1", message_id=10, minutes_ago=5, now=now),
            _msg("加油！稳住", user_id="user2", message_id=11, minutes_ago=4, now=now),
        ]
        trigger, _ = _check_emotional_gap(msgs, msgs[-1], BOT_USER_ID, now)
        assert trigger is None

    def test_recent_distress_ignored(self):
        now = _now()
        msgs = [
            _msg("想哭", user_id="user1", message_id=10, minutes_ago=1, now=now),
        ]
        trigger, _ = _check_emotional_gap(msgs, msgs[-1], BOT_USER_ID, now)
        assert trigger is None

    def test_english_distress(self):
        now = _now()
        msgs = [
            _msg("I can't take it anymore, falling apart", user_id="user1", message_id=10, minutes_ago=5, now=now),
        ]
        trigger, _ = _check_emotional_gap(msgs, msgs[-1], BOT_USER_ID, now)
        assert trigger is not None


# ============================================================
# Suppression penalties
# ============================================================

class TestPenalties:
    def test_bot_in_last_5(self):
        now = _now()
        msgs = [
            _msg(user_id="user1", message_id=1, minutes_ago=20, now=now),
            _msg(user_id=BOT_USER_ID, message_id=2, minutes_ago=15, now=now),
            _msg(user_id="user2", message_id=3, minutes_ago=10, now=now),
            _msg(user_id="user1", message_id=4, minutes_ago=5, now=now),
            _msg(user_id="user3", message_id=5, minutes_ago=1, now=now),
        ]
        penalties = _compute_penalties(msgs, BOT_USER_ID, now, True)
        assert "bot_in_last_5" in penalties
        assert penalties["bot_in_last_5"] == -0.5

    def test_bot_spoke_recently(self):
        now = _now()
        msgs = [
            _msg(user_id=BOT_USER_ID, message_id=1, minutes_ago=5, now=now),
            _msg(user_id="user1", message_id=2, minutes_ago=4, now=now),
            _msg(user_id="user2", message_id=3, minutes_ago=3, now=now),
            _msg(user_id="user3", message_id=4, minutes_ago=2, now=now),
            _msg(user_id="user4", message_id=5, minutes_ago=1, now=now),
            _msg(user_id="user5", message_id=6, minutes_ago=0, now=now),
        ]
        penalties = _compute_penalties(msgs, BOT_USER_ID, now, True)
        assert "bot_recent" in penalties
        assert penalties["bot_recent"] == -0.3

    def test_bot_not_recent_no_penalty(self):
        now = _now()
        msgs = [
            _msg(user_id=BOT_USER_ID, message_id=1, minutes_ago=20, now=now),
            _msg(user_id="user1", message_id=2, minutes_ago=1, now=now),
        ]
        penalties = _compute_penalties(msgs, BOT_USER_ID, now, True)
        assert "bot_recent" not in penalties

    def test_high_message_rate(self):
        now = _now()
        # >15 msgs in 5 min → rate > 3/min
        msgs = [
            _msg(user_id=f"u{i}", message_id=i, minutes_ago=i * 0.2, now=now)
            for i in range(20)
        ]
        penalties = _compute_penalties(msgs, BOT_USER_ID, now, True)
        assert "high_rate" in penalties

    def test_normal_rate_no_penalty(self):
        now = _now()
        msgs = [
            _msg(user_id="u1", message_id=1, minutes_ago=4, now=now),
            _msg(user_id="u2", message_id=2, minutes_ago=3, now=now),
            _msg(user_id="u3", message_id=3, minutes_ago=2, now=now),
        ]
        penalties = _compute_penalties(msgs, BOT_USER_ID, now, True)
        assert "high_rate" not in penalties

    def test_private_conversation_abab(self):
        now = _now()
        msgs = [
            _msg(user_id="alice", message_id=1, minutes_ago=4, now=now),
            _msg(user_id="bob", message_id=2, minutes_ago=3, now=now),
            _msg(user_id="alice", message_id=3, minutes_ago=2, now=now),
            _msg(user_id="bob", message_id=4, minutes_ago=1, now=now),
        ]
        penalties = _compute_penalties(msgs, BOT_USER_ID, now, True)
        assert "private_conversation" in penalties
        assert penalties["private_conversation"] == -0.4

    def test_no_private_conversation_3_users(self):
        now = _now()
        msgs = [
            _msg(user_id="alice", message_id=1, minutes_ago=4, now=now),
            _msg(user_id="bob", message_id=2, minutes_ago=3, now=now),
            _msg(user_id="charlie", message_id=3, minutes_ago=2, now=now),
            _msg(user_id="alice", message_id=4, minutes_ago=1, now=now),
        ]
        penalties = _compute_penalties(msgs, BOT_USER_ID, now, True)
        assert "private_conversation" not in penalties

    def test_tension_markers(self):
        now = _now()
        msgs = [
            _msg(content="shut up already", user_id="u1", message_id=1, minutes_ago=2, now=now),
        ]
        penalties = _compute_penalties(msgs, BOT_USER_ID, now, True)
        assert "tension" in penalties
        assert penalties["tension"] == -0.6

    def test_no_tension_no_penalty(self):
        now = _now()
        msgs = [
            _msg(content="nice weather today", user_id="u1", message_id=1, minutes_ago=2, now=now),
        ]
        penalties = _compute_penalties(msgs, BOT_USER_ID, now, True)
        assert "tension" not in penalties

    def test_outside_send_window(self):
        now = _now()
        msgs = [_msg(user_id="u1", message_id=1, minutes_ago=1, now=now)]
        penalties = _compute_penalties(msgs, BOT_USER_ID, now, False)
        assert "outside_window" in penalties
        assert penalties["outside_window"] == -1.0

    def test_inside_send_window_no_penalty(self):
        now = _now()
        msgs = [_msg(user_id="u1", message_id=1, minutes_ago=1, now=now)]
        penalties = _compute_penalties(msgs, BOT_USER_ID, now, True)
        assert "outside_window" not in penalties


# ============================================================
# Score aggregation + threshold
# ============================================================

class TestScoreAggregation:
    def test_name_mention_clean_passes_threshold(self):
        """Name mention (0.7) with no penalties should pass threshold (0.6)."""
        now = _now()
        msgs = [
            _msg("陈襄你觉得呢", user_id="user1", message_id=10, minutes_ago=0, now=now),
        ]
        result = evaluate_group_intervention(
            messages=msgs,
            current_message=msgs[-1],
            now=now,
        )
        assert result.should_intervene is True
        assert result.trigger is not None
        assert result.trigger.kind == "name_mention"
        assert result.final_score >= INTERVENTION_THRESHOLD

    def test_interest_match_alone_below_threshold(self):
        """Interest match (0.4) alone is below threshold (0.6)."""
        now = _now()
        msgs = [
            _msg("coffee is great today", user_id="user1", message_id=10, minutes_ago=0, now=now),
        ]
        result = evaluate_group_intervention(
            messages=msgs,
            current_message=msgs[-1],
            now=now,
        )
        assert result.should_intervene is False

    def test_name_mention_with_bot_recent_blocked(self):
        """Name mention (0.7) - bot_in_last_5 (-0.5) = 0.2 → blocked."""
        now = _now()
        msgs = [
            _msg(user_id=BOT_USER_ID, message_id=1, minutes_ago=2, now=now),
            _msg(user_id="user2", message_id=2, minutes_ago=1, now=now),
            _msg("陈襄你觉得呢", user_id="user1", message_id=3, minutes_ago=0, now=now),
        ]
        result = evaluate_group_intervention(
            messages=msgs,
            current_message=msgs[-1],
            now=now,
        )
        assert result.should_intervene is False
        assert "bot_in_last_5" in result.penalties

    def test_outside_window_always_blocks(self):
        now = _now()
        msgs = [
            _msg("陈襄来聊聊", user_id="user1", message_id=10, minutes_ago=0, now=now),
        ]
        result = evaluate_group_intervention(
            messages=msgs,
            current_message=msgs[-1],
            send_window_active=False,
            now=now,
        )
        assert result.should_intervene is False
        assert "outside_window" in result.penalties

    def test_bot_message_skipped(self):
        now = _now()
        msgs = [
            _msg("陈襄来聊聊", user_id=BOT_USER_ID, message_id=10, minutes_ago=0, now=now),
        ]
        result = evaluate_group_intervention(
            messages=msgs,
            current_message=msgs[-1],
            now=now,
        )
        assert result.should_intervene is False
        assert result.trigger is None

    def test_no_triggers_returns_silent(self):
        now = _now()
        msgs = [
            _msg("hello everyone", user_id="user1", message_id=10, minutes_ago=0, now=now),
        ]
        result = evaluate_group_intervention(
            messages=msgs,
            current_message=msgs[-1],
            now=now,
        )
        assert result.should_intervene is False
        assert result.trigger is None
        assert result.final_score == 0.0

    def test_highest_trigger_wins(self):
        """If name mention (0.7) and interest (0.4) both match, name mention wins."""
        now = _now()
        msgs = [
            _msg("陈襄你今天有喝coffee吗", user_id="user1", message_id=10, minutes_ago=0, now=now),
        ]
        result = evaluate_group_intervention(
            messages=msgs,
            current_message=msgs[-1],
            now=now,
        )
        assert result.should_intervene is True
        assert result.trigger.kind == "name_mention"

    def test_penalties_are_additive(self):
        """Multiple penalties stack."""
        now = _now()
        msgs = [
            _msg(content="shut up", user_id="u0", message_id=1, minutes_ago=3, now=now),
            _msg(user_id=BOT_USER_ID, message_id=2, minutes_ago=2, now=now),
            _msg(user_id="u2", message_id=3, minutes_ago=1.5, now=now),
            _msg(user_id="u3", message_id=4, minutes_ago=1, now=now),
            _msg("陈襄你好", user_id="u1", message_id=5, minutes_ago=0, now=now),
        ]
        result = evaluate_group_intervention(
            messages=msgs,
            current_message=msgs[-1],
            now=now,
        )
        # 0.7 (name) - 0.5 (bot_in_last_5) - 0.3 (bot_recent) - 0.6 (tension) < 0
        assert result.should_intervene is False
        assert len(result.penalties) >= 2


# ============================================================
# Re-evaluation / cancellation
# ============================================================

class TestReEvaluation:
    def test_cancel_on_3_new_messages(self):
        trigger = InterventionTrigger(kind="name_mention", score=0.7, delay_range=(30, 60))
        new_msgs = [_msg(content="a"), _msg(content="b"), _msg(content="c")]
        assert should_cancel_intervention(messages_since_trigger=new_msgs, trigger=trigger) is True

    def test_no_cancel_with_1_message(self):
        trigger = InterventionTrigger(kind="name_mention", score=0.7, delay_range=(30, 60))
        new_msgs = [_msg(content="a")]
        assert should_cancel_intervention(messages_since_trigger=new_msgs, trigger=trigger) is False

    def test_cancel_unanswered_question_if_answered(self):
        trigger = InterventionTrigger(kind="unanswered_question", score=0.4, delay_range=(30, 60))
        new_msgs = [_msg(content="here's the answer")]
        assert should_cancel_intervention(messages_since_trigger=new_msgs, trigger=trigger) is True

    def test_no_cancel_unanswered_question_if_no_reply(self):
        trigger = InterventionTrigger(kind="unanswered_question", score=0.4, delay_range=(30, 60))
        assert should_cancel_intervention(messages_since_trigger=[], trigger=trigger) is False

    def test_cancel_emotional_gap_if_support_given(self):
        trigger = InterventionTrigger(kind="emotional_gap", score=0.4, delay_range=(30, 60))
        new_msgs = [_msg(content="加油！你可以的")]
        assert should_cancel_intervention(messages_since_trigger=new_msgs, trigger=trigger) is True

    def test_no_cancel_emotional_gap_without_support(self):
        trigger = InterventionTrigger(kind="emotional_gap", score=0.4, delay_range=(30, 60))
        new_msgs = [_msg(content="lol nice")]
        assert should_cancel_intervention(messages_since_trigger=new_msgs, trigger=trigger) is False


# ============================================================
# Delay computation
# ============================================================

class TestDelay:
    def test_name_mention_delay_range(self):
        now = _now()
        msgs = [_msg("陈襄你觉得呢", user_id="user1", message_id=10, minutes_ago=0, now=now)]
        random.seed(42)
        result = evaluate_group_intervention(messages=msgs, current_message=msgs[-1], now=now)
        assert result.should_intervene is True
        assert 30 <= result.delay_seconds <= 60

    def test_silent_result_has_zero_delay(self):
        now = _now()
        msgs = [_msg("hello", user_id="user1", message_id=10, minutes_ago=0, now=now)]
        result = evaluate_group_intervention(messages=msgs, current_message=msgs[-1], now=now)
        assert result.should_intervene is False
        assert result.delay_seconds == 0.0

    def test_below_threshold_has_zero_delay(self):
        now = _now()
        msgs = [
            _msg(user_id=BOT_USER_ID, message_id=1, minutes_ago=2, now=now),
            _msg("陈襄", user_id="user1", message_id=2, minutes_ago=0, now=now),
        ]
        result = evaluate_group_intervention(messages=msgs, current_message=msgs[-1], now=now)
        if not result.should_intervene:
            assert result.delay_seconds == 0.0

    def test_delay_varies_between_calls(self):
        """Delay should have randomness (not always the same)."""
        now = _now()
        msgs = [_msg("陈襄你觉得呢", user_id="user1", message_id=10, minutes_ago=0, now=now)]
        delays = set()
        for seed in range(10):
            random.seed(seed)
            result = evaluate_group_intervention(messages=msgs, current_message=msgs[-1], now=now)
            if result.should_intervene:
                delays.add(round(result.delay_seconds, 2))
        assert len(delays) > 1  # randomness


# ============================================================
# Integration / edge cases
# ============================================================

class TestEdgeCases:
    def test_empty_messages(self):
        now = _now()
        result = evaluate_group_intervention(
            messages=[],
            current_message={},
            now=now,
        )
        assert result.should_intervene is False

    def test_current_message_from_bot(self):
        now = _now()
        msg = _msg("陈襄来了", user_id=BOT_USER_ID, message_id=1, minutes_ago=0, now=now)
        result = evaluate_group_intervention(
            messages=[msg],
            current_message=msg,
            now=now,
        )
        assert result.should_intervene is False

    def test_result_dataclass_fields(self):
        now = _now()
        msgs = [_msg("陈襄你好", user_id="user1", message_id=10, minutes_ago=0, now=now)]
        result = evaluate_group_intervention(messages=msgs, current_message=msgs[-1], now=now)
        assert isinstance(result, InterventionResult)
        assert isinstance(result.penalties, dict)
        assert isinstance(result.final_score, float)
        assert isinstance(result.raw_score, float)

    def test_missing_created_at_doesnt_crash(self):
        now = _now()
        msg = {"content": "有人知道吗？", "user_id": "user1", "message_id": 1}
        msgs = [msg]
        # Should not raise
        result = evaluate_group_intervention(
            messages=msgs,
            current_message=msg,
            now=now,
        )
        assert isinstance(result, InterventionResult)
