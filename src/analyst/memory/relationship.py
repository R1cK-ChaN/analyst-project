"""Pure rule-based relationship state update logic.

No I/O — all functions take current state + signals and return update dicts.
"""

from __future__ import annotations

import re
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from analyst.storage.sqlite_records import (
    CompanionRelationshipStateRecord,
    NicknameEntry,
)

from .profile import RelationshipSignalUpdate

# ---------------------------------------------------------------------------
# Stage thresholds & configuration
# ---------------------------------------------------------------------------

_STAGE_THRESHOLDS: list[tuple[str, str, float]] = [
    ("stranger", "acquaintance", 0.15),
    ("acquaintance", "familiar", 0.40),
    ("familiar", "close", 0.70),
]

_STAGE_COOLDOWN = timedelta(hours=48)

_MOOD_VALENCE: dict[str, int] = {
    # positive
    "optimistic": 1,
    "happy": 1,
    "excited": 1,
    "relaxed": 1,
    "content": 1,
    "calm": 1,
    # negative
    "anxious": -1,
    "stressed": -1,
    "burned_out": -1,
    "sad": -1,
    "overwhelmed": -1,
    "defeated": -1,
    "panicking": -1,
    "frustrated": -1,
    "exhausted": -1,
    "numb": -1,
    # neutral
    "cautious": 0,
    "tired": 0,
    "neutral": 0,
}

_NICKNAME_FOR_AI_PATTERN = re.compile(
    r"(?:用户|他|她|对方)叫我[「「\"']?(.+?)[」」\"']?$"
)
_NICKNAME_FOR_USER_PATTERN = re.compile(
    r"(?:我叫(?:他|她|用户))[「「\"']?(.+?)[」」\"']?$"
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_relationship_update(
    current: CompanionRelationshipStateRecord,
    *,
    signal: RelationshipSignalUpdate,
    now: datetime,
) -> dict[str, Any]:
    """Compute all relationship state updates for this turn.

    Returns a dict of kwargs suitable for ``store.update_companion_relationship_state()``.
    """
    updates: dict[str, Any] = {}
    today_str = now.strftime("%Y-%m-%d")

    # 1. Streak
    streak = _update_streak(current.streak_days, current.last_interaction_date, today_str)
    updates["streak_days"] = streak
    updates["last_interaction_date"] = today_str

    # 2. Turns & session average
    new_turns = current.total_turns + 1
    alpha = 0.1
    new_avg = current.avg_session_turns * (1 - alpha) + 1.0 * alpha if current.avg_session_turns > 0 else 1.0
    updates["total_turns"] = new_turns
    updates["avg_session_turns"] = round(new_avg, 2)

    # 3. Intimacy
    delta = _compute_intimacy_delta(signal, current)
    new_intimacy = min(1.0, current.intimacy_level + delta)
    updates["intimacy_level"] = round(new_intimacy, 4)

    # 4. Stage transition
    transition = _maybe_transition_stage(
        current.relationship_stage,
        new_intimacy,
        current.last_stage_transition_at,
        now,
    )
    if transition is not None:
        updates["relationship_stage"] = transition[0]
        updates["last_stage_transition_at"] = transition[1]

    # 5. Mood history & emotional trend
    mood_history = list(current.mood_history)
    if signal.current_mood:
        mood_history = _update_mood_history(mood_history, signal.current_mood)
    updates["mood_history"] = mood_history
    updates["emotional_trend"] = _compute_emotional_trend(mood_history)

    # 6. Nicknames
    nicknames = _update_nicknames(
        list(current.nicknames),
        signal,
    )
    if nicknames != current.nicknames:
        updates["nicknames"] = nicknames

    return updates


def extract_nicknames_from_facts(facts: list[str]) -> list[NicknameEntry]:
    """Extract structured NicknameEntry objects from personal_facts strings.

    Recognizes patterns like "用户叫我小襄" and "我叫他哥哥".
    """
    entries: list[NicknameEntry] = []
    for fact in facts:
        m = _NICKNAME_FOR_AI_PATTERN.search(fact)
        if m:
            entries.append(NicknameEntry(
                name=m.group(1).strip(),
                target="ai",
                created_by="user",
                frequency=1,
            ))
            continue
        m = _NICKNAME_FOR_USER_PATTERN.search(fact)
        if m:
            entries.append(NicknameEntry(
                name=m.group(1).strip(),
                target="user",
                created_by="ai",
                frequency=1,
            ))
    return entries


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _update_streak(current_streak: int, last_date: str, today: str) -> int:
    """Update streak_days based on interaction gap."""
    if not last_date:
        return 1
    if last_date == today:
        return max(current_streak, 1)
    try:
        last = datetime.strptime(last_date, "%Y-%m-%d").date()
        now = datetime.strptime(today, "%Y-%m-%d").date()
        gap = (now - last).days
    except ValueError:
        return 1
    if gap == 1:
        return current_streak + 1
    return 1


def _compute_intimacy_delta(
    signal: RelationshipSignalUpdate,
    current: CompanionRelationshipStateRecord,
) -> float:
    """Compute per-turn intimacy increment from signals."""
    delta = 0.003  # base per-turn
    if signal.is_personal_sharing:
        delta += 0.008
    if signal.is_late_night:
        delta += 0.005
    if signal.topic_depth_score > 1.5:
        delta += 0.004
    if current.streak_days > 3:
        delta += 0.002
    return delta


def _maybe_transition_stage(
    current_stage: str,
    intimacy: float,
    last_transition_at: str,
    now: datetime,
) -> tuple[str, str] | None:
    """Check if stage should transition. Returns (new_stage, transition_time) or None."""
    # Enforce cooldown
    if last_transition_at:
        try:
            last_t = datetime.fromisoformat(last_transition_at)
            if last_t.tzinfo is None:
                last_t = last_t.replace(tzinfo=timezone.utc)
            if (now - last_t) < _STAGE_COOLDOWN:
                return None
        except (ValueError, TypeError):
            pass

    for from_stage, to_stage, threshold in _STAGE_THRESHOLDS:
        if current_stage == from_stage and intimacy >= threshold:
            return (to_stage, now.isoformat())
    return None


def _update_mood_history(history: list[str], new_mood: str) -> list[str]:
    """Append mood, cap at 10 (FIFO)."""
    result = list(history)
    result.append(new_mood)
    return result[-10:]


def _compute_emotional_trend(history: list[str]) -> str:
    """Compute trend from mood valence sequence.

    Compares average valence of last 3 moods vs earlier moods.
    Returns "improving", "declining", "stable", or "" if insufficient data.
    """
    if len(history) < 3:
        return ""
    valences = [_MOOD_VALENCE.get(m, 0) for m in history]
    recent = valences[-3:]
    earlier = valences[:-3] if len(valences) > 3 else valences[:len(valences) - 3]
    recent_avg = sum(recent) / len(recent)
    if not earlier:
        # Only 3 moods — compare first vs last
        if recent_avg > 0.3:
            return "stable"
        if recent_avg < -0.3:
            return "stable"
        return "stable"
    earlier_avg = sum(earlier) / len(earlier)
    delta = recent_avg - earlier_avg
    if delta > 0.3:
        return "improving"
    if delta < -0.3:
        return "declining"
    return "stable"


def _update_nicknames(
    current: list[dict],
    signal: RelationshipSignalUpdate,
) -> list[dict]:
    """Update nickname list from signal. Returns new list."""
    if not signal.nickname_for_ai and not signal.nickname_for_user:
        return current

    result = list(current)

    for name, target, created_by in [
        (signal.nickname_for_ai, "ai", "user"),
        (signal.nickname_for_user, "user", "ai"),
    ]:
        if not name:
            continue
        found = False
        for i, entry in enumerate(result):
            if entry.get("name") == name and entry.get("target") == target:
                result[i] = {**entry, "frequency": entry.get("frequency", 0) + 1}
                found = True
                break
        if not found:
            result.append(asdict(NicknameEntry(
                name=name,
                target=target,
                created_by=created_by,
                frequency=1,
            )))

    return result[-10:]
