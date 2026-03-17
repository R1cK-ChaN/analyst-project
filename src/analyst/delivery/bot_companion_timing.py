from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from analyst.contracts import utc_now
from analyst.storage import SQLiteEngineStore

from .bot_constants import (
    COMPANION_CHECKIN_SEND_WINDOW_END_HOUR,
    COMPANION_CHECKIN_SEND_WINDOW_START_HOUR,
    COMPANION_LOCAL_TIMEZONE,
    DEEP_STORY_MIN_CHARS,
    DEEP_STORY_MIN_LINES,
    EMOTIONAL_CUE_TOKENS,
    INSTANT_REPLY_MAX_CHARS,
)
from .companion_schedule import build_companion_schedule_context

def _contains_emotional_cue(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in EMOTIONAL_CUE_TOKENS)

def _reply_timing_bucket(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return "instant"
    if stripped.count("\n") + 1 >= DEEP_STORY_MIN_LINES or len(stripped) >= DEEP_STORY_MIN_CHARS:
        return "deep_story"
    if _contains_emotional_cue(stripped):
        return "emotional"
    if len(stripped) <= INSTANT_REPLY_MAX_CHARS:
        return "instant"
    return "normal"

def _first_reply_delay_seconds(text: str, *, has_image: bool = False) -> float:
    if has_image:
        return 0.0
    stripped = text.strip()
    if not stripped:
        return 0.0
    bucket = _reply_timing_bucket(stripped)
    if bucket == "instant":
        return min(0.4, 0.05 + len(stripped) * 0.02)
    if bucket == "emotional":
        return min(3.5, 2.0 + min(len(stripped), 180) / 120.0)
    if bucket == "deep_story":
        return min(5.0, 3.0 + min(len(stripped), 320) / 160.0)
    return min(1.8, 0.8 + min(len(stripped), 120) / 120.0)

def evaluate_relationship_checkin_kind(
    relationship: Any,
    *,
    last_user_message_at: str | None = None,
    now: Any = None,
) -> str:
    """Determine if relationship state warrants a proactive check-in.

    Returns a check-in kind string or "" if none needed.
    Priority: streak_save > emotional_concern > stage_milestone.
    """
    if relationship is None:
        return ""
    stage = str(getattr(relationship, "relationship_stage", "stranger") or "stranger")
    streak = int(getattr(relationship, "streak_days", 0) or 0)
    prev_stage = str(getattr(relationship, "previous_stage", "") or "")
    last_date = str(getattr(relationship, "last_interaction_date", "") or "")
    # Compute emotional_trend from mood_history
    mood_history = getattr(relationship, "mood_history", None) or []
    emotional_trend = ""
    if mood_history and len(mood_history) >= 3:
        try:
            from analyst.memory.relationship import _compute_emotional_trend
            emotional_trend = _compute_emotional_trend(mood_history, now=now)
        except Exception:
            pass

    # Streak about to break: had a streak of 3+ days and last interaction was yesterday
    if streak >= 3 and last_date and now is not None:
        try:
            from datetime import datetime as _dt
            last = _dt.strptime(last_date, "%Y-%m-%d").date()
            local_now = _companion_local_now(now)
            gap = (local_now.date() - last).days
            if gap == 1:
                return "streak_save"
        except (ValueError, TypeError):
            pass

    # Emotional trend declining → proactive concern (separate from follow_up)
    if emotional_trend == "declining" and stage not in ("stranger",):
        return "emotional_concern"

    # Stage milestone: just transitioned upward (previous_stage is lower)
    _ORDER = {"stranger": 0, "acquaintance": 1, "familiar": 2, "close": 3}
    if prev_stage and _ORDER.get(prev_stage, 0) < _ORDER.get(stage, 0):
        return "stage_milestone"

    return ""


def _needs_emotional_follow_up(text: str, profile: Any) -> bool:
    if _contains_emotional_cue(text):
        return True
    stress_level = str(getattr(profile, "stress_level", "") or "").lower()
    emotional_trend = str(getattr(profile, "emotional_trend", "") or "").lower()
    current_mood = str(getattr(profile, "current_mood", "") or "").lower()
    return (
        stress_level in {"high", "critical"}
        or emotional_trend == "declining"
        or current_mood in {"anxious", "panicking", "burned_out", "defeated", "tired"}
    )

def _telegram_chat_id_from_channel(channel: str) -> int | None:
    prefix, _, raw_chat_id = str(channel).partition(":")
    if prefix != "telegram" or not raw_chat_id:
        return None
    try:
        return int(raw_chat_id)
    except ValueError:
        return None

def _companion_local_now(now: datetime) -> datetime:
    return now.astimezone(COMPANION_LOCAL_TIMEZONE)

def _minutes_since_midnight(moment: datetime) -> int:
    return moment.hour * 60 + moment.minute

def _is_weekend(moment: datetime) -> bool:
    return moment.weekday() >= 5

def _derive_companion_routine_state(now: datetime) -> str:
    local_now = _companion_local_now(now)
    minutes = _minutes_since_midnight(local_now)
    if _is_weekend(local_now):
        if minutes < 9 * 60:
            return "sleep"
        if minutes < 22 * 60 + 30:
            return "weekend_day"
        return "late_night"
    if minutes < 6 * 60 + 30:
        return "sleep"
    if minutes < 8 * 60:
        return "morning"
    if minutes < 9 * 60 + 30:
        return "commute"
    if minutes < 12 * 60:
        return "work"
    if minutes < 13 * 60 + 30:
        return "lunch"
    if minutes < 18 * 60 + 30:
        return "work"
    if minutes < 22 * 60 + 30:
        return "evening"
    return "late_night"

def _routine_checkin_kind(now: datetime) -> str:
    local_now = _companion_local_now(now)
    minutes = _minutes_since_midnight(local_now)
    if _is_weekend(local_now):
        if 11 * 60 <= minutes < 18 * 60:
            return "weekend"
        return ""
    if 7 * 60 + 15 <= minutes < 9 * 60:
        return "morning"
    if 19 * 60 <= minutes < 21 * 60:
        return "evening"
    return ""

def _parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=COMPANION_LOCAL_TIMEZONE)
    return parsed

def _is_same_local_day(value: str, now: datetime) -> bool:
    parsed = _parse_iso_datetime(value)
    if parsed is None:
        return False
    return _companion_local_now(parsed).date() == _companion_local_now(now).date()

def _lifestyle_ping_sent_at(lifestyle_state: Any, kind: str) -> str:
    normalized = str(kind).strip().lower()
    if normalized == "morning":
        return str(getattr(lifestyle_state, "last_morning_checkin_at", "") or "")
    if normalized == "evening":
        return str(getattr(lifestyle_state, "last_evening_checkin_at", "") or "")
    if normalized == "weekend":
        return str(getattr(lifestyle_state, "last_weekend_checkin_at", "") or "")
    return ""

def _is_within_checkin_send_window(now: datetime) -> bool:
    local_now = _companion_local_now(now)
    return COMPANION_CHECKIN_SEND_WINDOW_START_HOUR <= local_now.hour < COMPANION_CHECKIN_SEND_WINDOW_END_HOUR

def _next_checkin_window_start(now: datetime) -> datetime:
    local_now = _companion_local_now(now)
    candidate = local_now.replace(
        hour=COMPANION_CHECKIN_SEND_WINDOW_START_HOUR,
        minute=0,
        second=0,
        microsecond=0,
    )
    if local_now.hour >= COMPANION_CHECKIN_SEND_WINDOW_END_HOUR:
        candidate = candidate + timedelta(days=1)
    elif local_now.hour < COMPANION_CHECKIN_SEND_WINDOW_START_HOUR:
        candidate = candidate
    else:
        candidate = local_now
    return candidate.astimezone(now.tzinfo or COMPANION_LOCAL_TIMEZONE)

def _same_day_retry_due(now: datetime) -> datetime | None:
    local_now = _companion_local_now(now)
    retry_local = local_now + timedelta(hours=1)
    if retry_local.date() != local_now.date():
        return None
    if retry_local.hour >= COMPANION_CHECKIN_SEND_WINDOW_END_HOUR:
        return None
    return retry_local.astimezone(now.tzinfo or COMPANION_LOCAL_TIMEZONE)

def _cooldown_until(now: datetime) -> datetime:
    return now + timedelta(days=7)

def _refresh_companion_lifestyle_state(
    store: SQLiteEngineStore,
    *,
    client_id: str,
    channel_id: str,
    thread_id: str,
    now: datetime,
) -> Any:
    current = store.get_companion_lifestyle_state(
        client_id=client_id,
        channel=channel_id,
        thread_id=thread_id,
    )
    routine_state = _derive_companion_routine_state(now)
    last_state_changed_at = current.last_state_changed_at
    if current.routine_state != routine_state:
        last_state_changed_at = now.isoformat()
    return store.upsert_companion_lifestyle_state(
        client_id=client_id,
        channel=channel_id,
        thread_id=thread_id,
        timezone_name="Asia/Singapore",
        home_base="Singapore",
        work_area="Tanjong Pagar",
        routine_state=routine_state,
        last_state_changed_at=last_state_changed_at,
    )

def _companion_local_context(
    store: SQLiteEngineStore,
    lifestyle_state: Any,
    now: datetime,
) -> str:
    local_now = _companion_local_now(now)
    day_type = "weekend" if _is_weekend(local_now) else "weekday"
    base = (
        f"timezone: Asia/Singapore\n"
        f"home_base: Singapore\n"
        f"work_area: Tanjong Pagar\n"
        f"local_time: {local_now.strftime('%Y-%m-%d %H:%M %A')} (Asia/Singapore)\n"
        f"day_type: {day_type}\n"
        f"routine_state: {getattr(lifestyle_state, 'routine_state', '')}"
    )
    schedule_context = build_companion_schedule_context(
        store,
        now=now,
        routine_state=str(getattr(lifestyle_state, "routine_state", "") or ""),
    )
    return f"{base}\n{schedule_context}"
