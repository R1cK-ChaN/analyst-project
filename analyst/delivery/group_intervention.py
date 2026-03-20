"""Group chat autonomous intervention scoring engine.

Pure-logic module — no I/O, fully testable in isolation.
Evaluates whether the bot should autonomously speak in a group chat
based on trigger signals and suppression penalties.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import datetime

from analyst.memory.service import (
    _GROUP_SUPPORT_MARKERS,
    _GROUP_TENSION_MARKERS,
    _count_markers,
    _message_mentions_display_name,
)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class InterventionTrigger:
    kind: str           # "name_mention" | "interest_match" | "unanswered_question" | "emotional_gap"
    score: float        # base score for this trigger
    delay_range: tuple[int, int]  # (min_seconds, max_seconds)


@dataclass(frozen=True)
class InterventionResult:
    should_intervene: bool
    trigger: InterventionTrigger | None
    final_score: float
    raw_score: float
    penalties: dict[str, float]
    delay_seconds: float
    trigger_message_id: int


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INTERVENTION_THRESHOLD = 0.6

PERSONA_INTEREST_KEYWORDS: dict[str, tuple[str, ...]] = {
    "companion": (
        "猫", "咖啡", "coffee", "jazz", "摄影", "下雨", "失眠",
        "猫猫", "拿铁", "胶片", "gym", "健身", "singapore",
        "tanjong pagar", "running",
    ),
}

MAX_INTEREST_TRIGGERS_PER_DAY = 3

BOT_DISPLAY_NAMES = ("陈襄", "Shawn Chan", "Shawn")
BOT_USER_ID = "assistant"

_DISTRESS_MARKERS = (
    "不想活", "活不下去", "想死", "没意思", "累了", "扛不住",
    "受不了", "崩溃", "好难过", "好痛苦", "想哭",
    "can't take it", "want to die", "give up", "so tired",
    "breaking down", "falling apart",
)

_QUESTION_MARKS = ("?", "？")

_MIN_GAP_SECONDS = 180  # 3 minutes


# ---------------------------------------------------------------------------
# Trigger evaluation helpers
# ---------------------------------------------------------------------------

def _check_name_mention(
    current_message: dict,
    bot_display_names: tuple[str, ...],
) -> InterventionTrigger | None:
    """Check if the message informally mentions the bot by display name."""
    text = str(current_message.get("content", ""))
    for name in bot_display_names:
        if _message_mentions_display_name(text, name):
            return InterventionTrigger(kind="name_mention", score=0.7, delay_range=(30, 60))
    return None


def _check_interest_match(
    current_message: dict,
    persona_mode: str,
    interest_triggers_today: int,
) -> InterventionTrigger | None:
    """Check if the message contains a keyword the persona finds interesting."""
    if interest_triggers_today >= MAX_INTEREST_TRIGGERS_PER_DAY:
        return None
    keywords = PERSONA_INTEREST_KEYWORDS.get(persona_mode, ())
    if not keywords:
        return None
    text = str(current_message.get("content", "")).casefold()
    for kw in keywords:
        if kw.casefold() in text:
            return InterventionTrigger(kind="interest_match", score=0.4, delay_range=(60, 180))
    return None


def _is_question(text: str) -> bool:
    return any(qm in text for qm in _QUESTION_MARKS)


def _message_age_seconds(msg: dict, now: datetime) -> float:
    """Return age of a message in seconds, or 0 if unparseable."""
    created = msg.get("created_at", "")
    if not created:
        return 0.0
    try:
        dt = datetime.fromisoformat(created)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=now.tzinfo)
        return max((now - dt).total_seconds(), 0.0)
    except (ValueError, TypeError):
        return 0.0


def _has_reply_after(messages: list[dict], target_index: int) -> bool:
    """Check whether any message after target_index exists (i.e. someone replied)."""
    return target_index < len(messages) - 1


def _check_unanswered_question(
    messages: list[dict],
    current_message: dict,
    bot_user_id: str,
    now: datetime,
) -> tuple[InterventionTrigger | None, int]:
    """Find a question message that is 3+ min old with no reply after it.

    Returns (trigger, trigger_message_id) or (None, 0).
    """
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.get("user_id") == bot_user_id:
            continue
        text = str(msg.get("content", ""))
        if not _is_question(text):
            continue
        age = _message_age_seconds(msg, now)
        if age < _MIN_GAP_SECONDS:
            continue
        if not _has_reply_after(messages, i):
            msg_id = msg.get("message_id", 0)
            return (
                InterventionTrigger(kind="unanswered_question", score=0.4, delay_range=(30, 60)),
                int(msg_id),
            )
    return None, 0


def _check_emotional_gap(
    messages: list[dict],
    current_message: dict,
    bot_user_id: str,
    now: datetime,
) -> tuple[InterventionTrigger | None, int]:
    """Find a distress message 3+ min old with no support response after it."""
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if msg.get("user_id") == bot_user_id:
            continue
        text = str(msg.get("content", ""))
        if not any(marker in text.casefold() for marker in _DISTRESS_MARKERS):
            continue
        age = _message_age_seconds(msg, now)
        if age < _MIN_GAP_SECONDS:
            continue
        # Check if anyone gave support after this message
        support_found = False
        for j in range(i + 1, len(messages)):
            if _count_markers(messages[j].get("content", ""), _GROUP_SUPPORT_MARKERS) > 0:
                support_found = True
                break
        if not support_found:
            msg_id = msg.get("message_id", 0)
            return (
                InterventionTrigger(kind="emotional_gap", score=0.4, delay_range=(30, 60)),
                int(msg_id),
            )
    return None, 0


# ---------------------------------------------------------------------------
# Suppression penalties
# ---------------------------------------------------------------------------

def _compute_penalties(
    messages: list[dict],
    bot_user_id: str,
    now: datetime,
    send_window_active: bool,
) -> dict[str, float]:
    """Compute additive penalty dict.  All values are <= 0."""
    penalties: dict[str, float] = {}

    # 1. Bot in last 5 messages
    last_5 = messages[-5:] if len(messages) >= 5 else messages
    if any(m.get("user_id") == bot_user_id for m in last_5):
        penalties["bot_in_last_5"] = -0.5

    # 2. Bot spoke < 10 min ago
    for msg in reversed(messages):
        if msg.get("user_id") == bot_user_id:
            age = _message_age_seconds(msg, now)
            if age < 600:
                penalties["bot_recent"] = -0.3
            break

    # 3. Message rate > 3/min in last 5 min
    recent_count = sum(
        1 for m in messages if _message_age_seconds(m, now) <= 300
    )
    if recent_count > 0:
        rate = recent_count / 5.0  # messages per minute
        if rate > 3:
            penalties["high_rate"] = -0.3

    # 4. Two people alternating 4+ messages (A-B-A-B)
    if len(messages) >= 4:
        tail = messages[-4:]
        users = [m.get("user_id") for m in tail]
        if (
            len(set(users)) == 2
            and users[0] == users[2]
            and users[1] == users[3]
            and users[0] != users[1]
        ):
            penalties["private_conversation"] = -0.4

    # 5. Tension markers in last 10 messages
    last_10 = messages[-10:] if len(messages) >= 10 else messages
    tension_count = sum(
        _count_markers(m.get("content", ""), _GROUP_TENSION_MARKERS)
        for m in last_10
    )
    if tension_count > 0:
        penalties["tension"] = -0.6

    # 6. Outside send window
    if not send_window_active:
        penalties["outside_window"] = -1.0

    return penalties


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------

def evaluate_group_intervention(
    *,
    messages: list[dict],
    current_message: dict,
    bot_display_names: tuple[str, ...] = BOT_DISPLAY_NAMES,
    persona_mode: str = "companion",
    send_window_active: bool = True,
    bot_user_id: str = BOT_USER_ID,
    interest_triggers_today: int = 0,
    now: datetime | None = None,
) -> InterventionResult:
    """Evaluate whether the bot should autonomously intervene in a group chat.

    Returns an InterventionResult with the decision and scoring breakdown.
    """
    if now is None:
        from analyst.contracts import utc_now
        now = utc_now()

    _silent = InterventionResult(
        should_intervene=False,
        trigger=None,
        final_score=0.0,
        raw_score=0.0,
        penalties={},
        delay_seconds=0.0,
        trigger_message_id=0,
    )

    # Skip if message is from bot
    if current_message.get("user_id") == bot_user_id:
        return _silent

    # Evaluate triggers — pick highest score
    trigger_message_id = current_message.get("message_id", 0)
    candidates: list[tuple[InterventionTrigger, int]] = []

    t = _check_name_mention(current_message, bot_display_names)
    if t is not None:
        candidates.append((t, int(trigger_message_id)))

    t = _check_interest_match(current_message, persona_mode, interest_triggers_today)
    if t is not None:
        candidates.append((t, int(trigger_message_id)))

    uq_trigger, uq_msg_id = _check_unanswered_question(messages, current_message, bot_user_id, now)
    if uq_trigger is not None:
        candidates.append((uq_trigger, uq_msg_id))

    eg_trigger, eg_msg_id = _check_emotional_gap(messages, current_message, bot_user_id, now)
    if eg_trigger is not None:
        candidates.append((eg_trigger, eg_msg_id))

    if not candidates:
        return _silent

    # Pick highest scoring trigger
    best_trigger, best_msg_id = max(candidates, key=lambda x: x[0].score)

    # Compute penalties
    penalties = _compute_penalties(messages, bot_user_id, now, send_window_active)

    raw_score = best_trigger.score
    final_score = raw_score + sum(penalties.values())

    if final_score < INTERVENTION_THRESHOLD:
        return InterventionResult(
            should_intervene=False,
            trigger=best_trigger,
            final_score=final_score,
            raw_score=raw_score,
            penalties=penalties,
            delay_seconds=0.0,
            trigger_message_id=best_msg_id,
        )

    # Schedule with random delay
    lo, hi = best_trigger.delay_range
    delay = random.uniform(lo, hi)

    return InterventionResult(
        should_intervene=True,
        trigger=best_trigger,
        final_score=final_score,
        raw_score=raw_score,
        penalties=penalties,
        delay_seconds=delay,
        trigger_message_id=best_msg_id,
    )


# ---------------------------------------------------------------------------
# Re-evaluation (cancel check after delay)
# ---------------------------------------------------------------------------

def should_cancel_intervention(
    *,
    messages_since_trigger: list[dict],
    trigger: InterventionTrigger,
) -> bool:
    """After the delay, check if the intervention should be cancelled.

    Called with messages that arrived *after* the trigger message.
    """
    # Topic moved on: 3+ new messages
    if len(messages_since_trigger) >= 3:
        return True

    if trigger.kind == "unanswered_question":
        # Someone answered the question
        if len(messages_since_trigger) >= 1:
            return True

    if trigger.kind == "emotional_gap":
        # Someone gave support
        for msg in messages_since_trigger:
            if _count_markers(msg.get("content", ""), _GROUP_SUPPORT_MARKERS) > 0:
                return True

    return False
