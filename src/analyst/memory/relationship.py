"""Pure rule-based relationship state update logic.

No I/O — all functions take current state + signals and return update dicts.
"""

from __future__ import annotations

import json
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

_INTIMACY_DECAY_PER_DAY = 0.01
_INTIMACY_DECAY_GRACE_DAYS = 1  # no decay for 1-day gaps (same/next day)

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

# Topic category → tendency it nudges
_CATEGORY_TENDENCY_MAP: dict[str, str] = {
    "mood / emotional": "confidant",
    "relationships / people": "confidant",
    "joke / banter": "friend",
    "meal / food": "friend",
    "photos / media": "friend",
    "planning / scheduling": "mentor",
    "work / office": "mentor",
    "travel / outing": "friend",
    "market / finance": "mentor",
}

_TENDENCY_NUDGE_AMOUNT = 0.02

# Interaction mode → tendency
_INTERACTION_MODE_TENDENCY_MAP: dict[str, str] = {
    "seeking_advice": "mentor",
    "venting": "confidant",
    "flirting": "romantic",
    "curious_about_ai": "friend",
}
_LATE_NIGHT_TENDENCY_NUDGES: dict[str, float] = {
    "confidant": 0.015,
    "romantic": 0.01,
}

_NICKNAME_FOR_AI_PATTERN = re.compile(
    r"(?:用户|他|她|对方)叫我[「「\"']?(.+?)[」」\"']?(?:$|[，。,.])"
)
_NICKNAME_FOR_USER_PATTERN = re.compile(
    r"(?:我叫(?:他|她|用户))[「「\"']?(.+?)[」」\"']?(?:$|[，。,.])"
)
# English patterns for personal_facts extraction
_EN_NICKNAME_FOR_AI_PATTERN = re.compile(
    r"(?:user |they |he |she )?calls? me [\"']?(.+?)[\"']?(?:$|[,.])",
    re.IGNORECASE,
)
_EN_NICKNAME_FOR_USER_PATTERN = re.compile(
    r"I call (?:them|him|her|the user) [\"']?(.+?)[\"']?(?:$|[,.])",
    re.IGNORECASE,
)

# Direct user text patterns — detect nickname assignments from raw messages
_USER_TEXT_NICKNAME_FOR_AI_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Chinese
    re.compile(r"(?:以后|从现在开始|从今天开始)?(?:就)?叫你[「「\"']?(.+?)[」」\"']?(?:吧|了|$|[，。！,.])", re.IGNORECASE),
    re.compile(r"(?:我要|我想)?(?:给你|帮你)?(?:取个|起个|取一个)?(?:名字|昵称|外号|绰号)[，,]?\s*(?:就)?叫[「「\"']?(.+?)[」」\"']?(?:吧|了|$|[，。！,.])", re.IGNORECASE),
    re.compile(r"你(?:就)?是(?:我们?的)?[「「\"']?(.+?)[」」\"']?(?:了|吧|$|[，。！,.])", re.IGNORECASE),
    # English — use $ or punctuation as terminators (not \s, which eats spaces in multi-word names)
    re.compile(r"(?:from now on,?\s*)?(?:I(?:'ll| will)?\s*)?call you [\"']?(.+?)[\"']?\s*$", re.IGNORECASE),
    re.compile(r"(?:from now on,?\s*)?you (?:are|'re)\s+(?:our |my )?[\"']?(.+?)[\"']?\s*(?:$|[,.])", re.IGNORECASE),
    re.compile(r"(?:I(?:'ll| will)?\s*)?(?:nick)?name you [\"']?(.+?)[\"']?\s*$", re.IGNORECASE),
    re.compile(r"(?:your (?:new )?(?:nick)?name is|let me call you) [\"']?(.+?)[\"']?\s*$", re.IGNORECASE),
)
_USER_TEXT_NICKNAME_FOR_USER_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Chinese
    re.compile(r"(?:以后|从现在开始)?(?:你)?叫我[「「\"']?(.+?)[」」\"']?(?:吧|了|$|[，。！,.])", re.IGNORECASE),
    re.compile(r"(?:以后|从现在开始)?(?:你)?(?:喊|称呼)我[「「\"']?(.+?)[」」\"']?(?:吧|了|$|[，。！,.])", re.IGNORECASE),
    # English
    re.compile(r"call me [\"']?(.+?)[\"']?\s*$", re.IGNORECASE),
    re.compile(r"(?:my (?:nick)?name is|I(?:'m| am)) [\"']?(.+?)[\"']?\s*$", re.IGNORECASE),
)

_MOOD_HISTORY_WINDOW = timedelta(hours=24)


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

    # 3. Intimacy (decay + growth)
    decayed = _apply_intimacy_decay(
        current.intimacy_level, current.last_interaction_date, today_str
    )
    delta = _compute_intimacy_delta(signal, current)
    new_intimacy = min(1.0, max(0.0, decayed + delta))
    updates["intimacy_level"] = round(new_intimacy, 4)

    # 3b. Track peak intimacy for cold outreach detection
    current_peak = getattr(current, "peak_intimacy_level", 0.0) or 0.0
    if new_intimacy > current_peak:
        updates["peak_intimacy_level"] = round(new_intimacy, 4)

    # 4. Stage transition (can also regress on heavy decay)
    transition = _maybe_transition_stage(
        current.relationship_stage,
        new_intimacy,
        current.last_stage_transition_at,
        now,
    )
    if transition is not None:
        updates["previous_stage"] = current.relationship_stage
        updates["relationship_stage"] = transition[0]
        updates["last_stage_transition_at"] = transition[1]

    # 5. Tendency distribution (with spike damping)
    tf, tr, tc, tm = _update_tendencies(
        current.tendency_friend,
        current.tendency_romantic,
        current.tendency_confidant,
        current.tendency_mentor,
        signal=signal,
    )
    # Apply damping if there's a primary nudge target this turn
    damping_json = getattr(current, "tendency_damping_json", "{}") or "{}"
    try:
        damping_state = json.loads(damping_json) if isinstance(damping_json, str) else {}
    except (json.JSONDecodeError, TypeError):
        damping_state = {}
    primary_target = _get_primary_nudge_target(signal)
    if primary_target:
        tendencies_dict = {
            "friend": current.tendency_friend,
            "romantic": current.tendency_romantic,
            "confidant": current.tendency_confidant,
            "mentor": current.tendency_mentor,
        }
        effective_amount, damping_state = apply_tendency_damping(
            tendencies_dict, primary_target, _TENDENCY_NUDGE_AMOUNT, damping_state,
        )
        if effective_amount != _TENDENCY_NUDGE_AMOUNT:
            # Recompute with damped amount
            tf, tr, tc, tm = current.tendency_friend, current.tendency_romantic, current.tendency_confidant, current.tendency_mentor
            tf, tr, tc, tm = _nudge(tf, tr, tc, tm, primary_target, effective_amount)
            if signal.is_personal_sharing:
                tf, tr, tc, tm = _nudge(tf, tr, tc, tm, "confidant", 0.015)
            if signal.is_late_night:
                for tendency, amount in _LATE_NIGHT_TENDENCY_NUDGES.items():
                    tf, tr, tc, tm = _nudge(tf, tr, tc, tm, tendency, amount)
            tf, tr, tc, tm = _normalize_tendencies(tf, tr, tc, tm)
        updates["tendency_damping_json"] = json.dumps(damping_state, ensure_ascii=False)
    updates["tendency_friend"] = tf
    updates["tendency_romantic"] = tr
    updates["tendency_confidant"] = tc
    updates["tendency_mentor"] = tm

    # 6. Mood history & emotional trend (timestamped entries)
    mood_history = list(current.mood_history)
    if signal.current_mood:
        mood_history = _update_mood_history(mood_history, signal.current_mood, now)
    updates["mood_history"] = mood_history
    updates["emotional_trend"] = _compute_emotional_trend(mood_history, now=now)

    # 7. Nicknames (from signal + frequency bump from user_text)
    nicknames = _update_nicknames(list(current.nicknames), signal)
    if signal.user_text:
        nicknames = _bump_nickname_frequency(nicknames, signal.user_text)
    if nicknames != current.nicknames:
        updates["nicknames"] = nicknames

    return updates


def extract_nicknames_from_facts(facts: list[str]) -> list[NicknameEntry]:
    """Extract structured NicknameEntry objects from personal_facts strings.

    Recognizes patterns like "用户叫我小襄", "我叫他哥哥",
    "user calls me Shawn", "I call them Boss".
    """
    entries: list[NicknameEntry] = []
    for fact in facts:
        # Chinese patterns
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
            continue
        # English patterns
        m = _EN_NICKNAME_FOR_AI_PATTERN.search(fact)
        if m:
            entries.append(NicknameEntry(
                name=m.group(1).strip(),
                target="ai",
                created_by="user",
                frequency=1,
            ))
            continue
        m = _EN_NICKNAME_FOR_USER_PATTERN.search(fact)
        if m:
            entries.append(NicknameEntry(
                name=m.group(1).strip(),
                target="user",
                created_by="ai",
                frequency=1,
            ))
    return entries


def detect_nickname_from_text(user_text: str) -> tuple[str | None, str | None]:
    """Detect nickname assignments from raw user message text.

    Returns (nickname_for_ai, nickname_for_user) — either or both may be None.
    """
    nickname_for_ai: str | None = None
    nickname_for_user: str | None = None

    for pattern in _USER_TEXT_NICKNAME_FOR_AI_PATTERNS:
        m = pattern.search(user_text)
        if m:
            candidate = m.group(1).strip()
            # Filter out overly long or empty matches
            if candidate and len(candidate) <= 20:
                nickname_for_ai = candidate
            break

    for pattern in _USER_TEXT_NICKNAME_FOR_USER_PATTERNS:
        m = pattern.search(user_text)
        if m:
            candidate = m.group(1).strip()
            if candidate and len(candidate) <= 20:
                nickname_for_user = candidate
            break

    return nickname_for_ai, nickname_for_user


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


def _apply_intimacy_decay(
    current_intimacy: float, last_date: str, today: str
) -> float:
    """Decay intimacy based on days of inactivity.

    No decay for same-day or next-day. After that, -0.01 per day of absence.
    """
    if not last_date or last_date == today:
        return current_intimacy
    try:
        last = datetime.strptime(last_date, "%Y-%m-%d").date()
        now = datetime.strptime(today, "%Y-%m-%d").date()
        gap = (now - last).days
    except ValueError:
        return current_intimacy
    if gap <= _INTIMACY_DECAY_GRACE_DAYS:
        return current_intimacy
    decay_days = gap - _INTIMACY_DECAY_GRACE_DAYS
    decayed = current_intimacy - (decay_days * _INTIMACY_DECAY_PER_DAY)
    return max(0.0, decayed)


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
    """Check if stage should transition (up or down). Returns (new_stage, ts) or None."""
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

    # Check upward transitions
    for from_stage, to_stage, threshold in _STAGE_THRESHOLDS:
        if current_stage == from_stage and intimacy >= threshold:
            return (to_stage, now.isoformat())

    # Check downward transitions (regression on decay)
    for from_stage, to_stage, threshold in reversed(_STAGE_THRESHOLDS):
        if current_stage == to_stage and intimacy < threshold * 0.7:
            return (from_stage, now.isoformat())

    return None


# ---------------------------------------------------------------------------
# Tendency distribution
# ---------------------------------------------------------------------------


def _get_primary_nudge_target(signal: RelationshipSignalUpdate) -> str:
    """Determine the primary tendency nudge target for this turn's signal."""
    if signal.interaction_mode:
        target = _INTERACTION_MODE_TENDENCY_MAP.get(signal.interaction_mode)
        if target:
            return target
    if signal.active_topic_category:
        target = _CATEGORY_TENDENCY_MAP.get(signal.active_topic_category)
        if target:
            return target
    return ""


def _update_tendencies(
    friend: float,
    romantic: float,
    confidant: float,
    mentor: float,
    *,
    signal: RelationshipSignalUpdate,
) -> tuple[float, float, float, float]:
    """Nudge tendency distribution based on interaction signals, then normalize."""
    tf, tr, tc, tm = friend, romantic, confidant, mentor

    # Topic category nudge
    if signal.active_topic_category:
        target = _CATEGORY_TENDENCY_MAP.get(signal.active_topic_category)
        if target:
            tf, tr, tc, tm = _nudge(tf, tr, tc, tm, target, _TENDENCY_NUDGE_AMOUNT)

    # Personal sharing → confidant
    if signal.is_personal_sharing:
        tf, tr, tc, tm = _nudge(tf, tr, tc, tm, "confidant", 0.015)

    # Late night → confidant + romantic
    if signal.is_late_night:
        for tendency, amount in _LATE_NIGHT_TENDENCY_NUDGES.items():
            tf, tr, tc, tm = _nudge(tf, tr, tc, tm, tendency, amount)

    # Interaction mode nudge
    if signal.interaction_mode:
        target = _INTERACTION_MODE_TENDENCY_MAP.get(signal.interaction_mode)
        if target:
            tf, tr, tc, tm = _nudge(tf, tr, tc, tm, target, _TENDENCY_NUDGE_AMOUNT)

    return _normalize_tendencies(tf, tr, tc, tm)


def _nudge(
    friend: float, romantic: float, confidant: float, mentor: float,
    target: str, amount: float,
) -> tuple[float, float, float, float]:
    """Add amount to the target tendency (before normalization)."""
    if target == "friend":
        friend += amount
    elif target == "romantic":
        romantic += amount
    elif target == "confidant":
        confidant += amount
    elif target == "mentor":
        mentor += amount
    return friend, romantic, confidant, mentor


def _normalize_tendencies(
    friend: float, romantic: float, confidant: float, mentor: float,
) -> tuple[float, float, float, float]:
    """Normalize so tendencies sum to 1.0. Returns rounded values."""
    total = friend + romantic + confidant + mentor
    if total <= 0:
        return (0.25, 0.25, 0.25, 0.25)
    return (
        round(friend / total, 4),
        round(romantic / total, 4),
        round(confidant / total, 4),
        round(mentor / total, 4),
    )


# ---------------------------------------------------------------------------
# Tendency spike damping
# ---------------------------------------------------------------------------

_DAMPING_DOMINANT_THRESHOLD = 0.35
_DAMPING_CONSECUTIVE_TO_CONFIRM = 3
_DAMPING_FACTOR = 0.5


def _get_dominant_tendency(tendencies: dict[str, float]) -> tuple[str, float]:
    """Return (name, ratio) of the dominant tendency."""
    if not tendencies:
        return ("friend", 0.25)
    name = max(tendencies, key=tendencies.get)  # type: ignore[arg-type]
    return (name, tendencies[name])


def apply_tendency_damping(
    tendencies: dict[str, float],
    nudge_target: str,
    nudge_amount: float,
    damping_state: dict,
) -> tuple[float, dict]:
    """Apply spike damping to a tendency nudge.

    Returns (effective_nudge_amount, updated_damping_state).
    """
    if not nudge_target or nudge_amount <= 0:
        return (nudge_amount, damping_state)

    state = dict(damping_state)
    dominant = state.get("dominant_20", "")
    dominant_ratio = float(state.get("dominant_ratio", 0.0))

    # Recompute dominant from current tendencies
    d_name, d_ratio = _get_dominant_tendency(tendencies)
    state["dominant_20"] = d_name
    state["dominant_ratio"] = round(d_ratio, 4)

    # If nudge aligns with dominant → normal, reset spike tracking
    if nudge_target == d_name:
        state["spike_target"] = ""
        state["spike_consecutive"] = 0
        state["accumulated_dampened"] = {}
        return (nudge_amount, state)

    # If no strong dominant pattern → normal nudge
    if d_ratio <= _DAMPING_DOMINANT_THRESHOLD:
        state["spike_target"] = ""
        state["spike_consecutive"] = 0
        state["accumulated_dampened"] = {}
        return (nudge_amount, state)

    # Opposing a strong dominant pattern
    current_spike = state.get("spike_target", "")
    consecutive = int(state.get("spike_consecutive", 0))
    accumulated = dict(state.get("accumulated_dampened", {}))

    if nudge_target != current_spike:
        # New spike direction — reset
        consecutive = 1
        accumulated = {nudge_target: nudge_amount * (1 - _DAMPING_FACTOR)}
        state["spike_target"] = nudge_target
        state["spike_consecutive"] = consecutive
        state["accumulated_dampened"] = accumulated
        return (nudge_amount * _DAMPING_FACTOR, state)

    # Same spike direction continuing
    consecutive += 1
    state["spike_consecutive"] = consecutive

    if consecutive >= _DAMPING_CONSECUTIVE_TO_CONFIRM:
        # Confirmed shift — apply full amount + accumulated dampened
        retroactive = float(accumulated.get(nudge_target, 0.0))
        state["spike_target"] = ""
        state["spike_consecutive"] = 0
        state["accumulated_dampened"] = {}
        return (nudge_amount + retroactive, state)

    # Still in ambiguous window — halve the nudge, accumulate the rest
    dampened_delta = nudge_amount * (1 - _DAMPING_FACTOR)
    accumulated[nudge_target] = float(accumulated.get(nudge_target, 0.0)) + dampened_delta
    state["accumulated_dampened"] = accumulated
    return (nudge_amount * _DAMPING_FACTOR, state)


# ---------------------------------------------------------------------------
# Mood history (timestamped entries)
# ---------------------------------------------------------------------------


def _mood_entry(mood: str, at: datetime) -> dict:
    """Create a timestamped mood entry."""
    return {"mood": mood, "at": at.isoformat()}


def _parse_mood_entry(entry: Any) -> tuple[str, datetime | None]:
    """Parse a mood entry. Handles both old format (str) and new format (dict)."""
    if isinstance(entry, str):
        return (entry, None)
    if isinstance(entry, dict):
        mood = entry.get("mood", "")
        at_str = entry.get("at", "")
        at_dt = None
        if at_str:
            try:
                at_dt = datetime.fromisoformat(at_str)
                if at_dt.tzinfo is None:
                    at_dt = at_dt.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                pass
        return (mood, at_dt)
    return ("", None)


def _update_mood_history(
    history: list, new_mood: str, now: datetime
) -> list[dict]:
    """Append timestamped mood, cap at 10 (FIFO)."""
    result = list(history)
    result.append(_mood_entry(new_mood, now))
    return result[-10:]


def _compute_emotional_trend(
    history: list, *, now: datetime | None = None
) -> str:
    """Compute trend from mood valence sequence.

    Only considers moods within the last 24h (if timestamps available).
    Compares average valence of last 3 moods vs earlier moods.
    Returns "improving", "declining", "stable", or "" if insufficient data.
    """
    # Filter to 24h window if timestamps are available
    if now is not None:
        cutoff = now - _MOOD_HISTORY_WINDOW
        filtered: list[str] = []
        for entry in history:
            mood, at_dt = _parse_mood_entry(entry)
            if not mood:
                continue
            if at_dt is not None and at_dt < cutoff:
                continue  # outside window
            filtered.append(mood)
    else:
        filtered = [_parse_mood_entry(e)[0] for e in history if _parse_mood_entry(e)[0]]

    if len(filtered) < 3:
        return ""
    valences = [_MOOD_VALENCE.get(m, 0) for m in filtered]
    recent = valences[-3:]
    earlier = valences[:-3]
    recent_avg = sum(recent) / len(recent)
    if not earlier:
        return "stable"
    earlier_avg = sum(earlier) / len(earlier)
    delta = recent_avg - earlier_avg
    if delta > 0.3:
        return "improving"
    if delta < -0.3:
        return "declining"
    return "stable"


# ---------------------------------------------------------------------------
# Nicknames
# ---------------------------------------------------------------------------


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


def _bump_nickname_frequency(
    nicknames: list[dict], user_text: str
) -> list[dict]:
    """Increment frequency for any known nickname that appears in user_text."""
    if not nicknames or not user_text:
        return nicknames
    result = list(nicknames)
    for i, entry in enumerate(result):
        name = entry.get("name", "")
        if name and name in user_text:
            result[i] = {**entry, "frequency": entry.get("frequency", 0) + 1}
    return result
