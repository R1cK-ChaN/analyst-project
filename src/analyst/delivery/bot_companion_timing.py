from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import random
from typing import Any
from zoneinfo import ZoneInfo

from analyst.contracts import utc_now
from analyst.storage import SQLiteEngineStore
from analyst.memory.companion_self_state import (
    build_companion_self_context,
)

from analyst.memory.topic_state import _is_acknowledgement, _collapse_whitespace

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


# ---------------------------------------------------------------------------
# Stage-aware send windows
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SendWindow:
    start_hour: int
    start_minute: int
    end_hour: int
    end_minute: int
    blocked: bool = False


_STAGE_SEND_WINDOWS: dict[str, SendWindow] = {
    "stranger": SendWindow(0, 0, 0, 0, blocked=True),
    "acquaintance": SendWindow(9, 0, 21, 0),
    "familiar": SendWindow(8, 0, 23, 0),
    "close": SendWindow(8, 0, 23, 30),
}
_CLOSE_ROMANTIC_LATE_WINDOW = SendWindow(8, 0, 1, 0)


def get_send_window(
    stage: str,
    *,
    tendency_romantic: float = 0.0,
    late_night_activity_pct: float = 0.0,
) -> SendWindow:
    if stage == "stranger":
        return _STAGE_SEND_WINDOWS["stranger"]
    if stage == "close" and tendency_romantic > 0.4 and late_night_activity_pct > 0.5:
        return _CLOSE_ROMANTIC_LATE_WINDOW
    return _STAGE_SEND_WINDOWS.get(stage, _STAGE_SEND_WINDOWS["acquaintance"])


def is_within_send_window(
    now: datetime,
    *,
    window: SendWindow,
    timezone_name: str = "Asia/Shanghai",
) -> bool:
    if window.blocked:
        return False
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = ZoneInfo("Asia/Shanghai")
    local_now = now.astimezone(tz)
    current_minutes = local_now.hour * 60 + local_now.minute
    start_minutes = window.start_hour * 60 + window.start_minute
    end_minutes = window.end_hour * 60 + window.end_minute
    if end_minutes > start_minutes:
        # Normal window (e.g., 08:00 - 23:30)
        return start_minutes <= current_minutes < end_minutes
    else:
        # Crosses midnight (e.g., 08:00 - 01:00)
        return current_minutes >= start_minutes or current_minutes < end_minutes


def compute_late_night_activity_pct(
    message_timestamps: list[str],
    timezone_name: str = "Asia/Shanghai",
) -> float:
    if not message_timestamps:
        return 0.0
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = ZoneInfo("Asia/Shanghai")
    late_count = 0
    total = 0
    for ts in message_timestamps:
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                from datetime import timezone as _tz
                dt = dt.replace(tzinfo=_tz.utc)
            local_dt = dt.astimezone(tz)
            total += 1
            if local_dt.hour >= 23 or local_dt.hour < 5:
                late_count += 1
        except (ValueError, TypeError):
            continue
    if total == 0:
        return 0.0
    return late_count / total

def _contains_emotional_cue(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in EMOTIONAL_CUE_TOKENS)

def _reply_timing_bucket(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return "instant"
    lowered = stripped.casefold()
    if _is_acknowledgement(stripped, lowered=lowered):
        return "seen_no_rush"
    if stripped.count("\n") + 1 >= DEEP_STORY_MIN_LINES or len(stripped) >= DEEP_STORY_MIN_CHARS:
        return "deep_story"
    if _contains_emotional_cue(stripped):
        return "emotional"
    if len(stripped) <= INSTANT_REPLY_MAX_CHARS:
        return "instant"
    return "normal"

def _seen_no_rush_delay(text: str) -> tuple[float, bool] | None:
    """If *text* is an acknowledgement, return ``(delay_seconds, is_long)``.

    Returns ``None`` when the message is not an acknowledgement.
    ``is_long`` is ``True`` ~20% of the time (60-180 s delay); otherwise
    ``False`` with a short 3-8 s pause.
    """
    stripped = text.strip()
    if not stripped:
        return None
    if _reply_timing_bucket(stripped) != "seen_no_rush":
        return None
    if random.random() < 0.2:
        return (random.uniform(60.0, 180.0), True)
    return (random.uniform(3.0, 8.0), False)


def _first_reply_delay_seconds(text: str, *, has_image: bool = False) -> float:
    if has_image:
        return random.uniform(3.0, 8.0)
    stripped = text.strip()
    if not stripped:
        return 0.0
    bucket = _reply_timing_bucket(stripped)
    if bucket == "seen_no_rush":
        # Deterministic short pause for plain callers; the probabilistic long
        # delay is handled via _seen_no_rush_delay at the call site.
        return random.uniform(3.0, 8.0)
    if bucket == "instant":
        return random.uniform(3.0, 6.0)
    if bucket == "emotional":
        return random.uniform(16.0, 28.0)
    if bucket == "deep_story":
        return random.uniform(24.0, 40.0)
    # normal
    return random.uniform(8.0, 14.0)

def evaluate_relationship_checkin_kind(
    relationship: Any,
    *,
    last_user_message_at: str | None = None,
    now: Any = None,
    outreach_metrics: Any = None,
    last_outreach_sent_at: str | None = None,
) -> str:
    """Determine if relationship state warrants a proactive check-in.

    Returns a check-in kind string or "" if none needed.
    Priority: streak_save > emotional_concern > stage_milestone > warm_up_share.
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

    # If response rate is very low and stage regressing, only allow warm_up_share
    metrics_rate = getattr(outreach_metrics, "response_rate", 1.0) if outreach_metrics else 1.0
    _ORDER = {"stranger": 0, "acquaintance": 1, "familiar": 2, "close": 3}
    is_regressing = prev_stage and _ORDER.get(prev_stage, 0) > _ORDER.get(stage, 0)
    if metrics_rate < 0.3 and is_regressing:
        if _should_warm_up_share(relationship, outreach_metrics, last_outreach_sent_at, now):
            return "warm_up_share"
        return ""

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
    if prev_stage and _ORDER.get(prev_stage, 0) < _ORDER.get(stage, 0):
        return "stage_milestone"

    # Warm-up share for cooling relationships (lower priority)
    if _should_warm_up_share(relationship, outreach_metrics, last_outreach_sent_at, now):
        return "warm_up_share"

    return ""


def _should_warm_up_share(
    relationship: Any,
    outreach_metrics: Any,
    last_outreach_sent_at: str | None,
    now: Any,
) -> bool:
    """Check if warm_up_share outreach should be triggered.

    ALL conditions must be true:
    1. Stage regressed OR intimacy decayed > 0.1 from peak
    2. Response rate < 0.4
    3. Last outreach >= 72 hours ago
    """
    if relationship is None or now is None:
        return False

    _ORDER = {"stranger": 0, "acquaintance": 1, "familiar": 2, "close": 3}
    stage = str(getattr(relationship, "relationship_stage", "stranger") or "stranger")
    prev_stage = str(getattr(relationship, "previous_stage", "") or "")
    intimacy = float(getattr(relationship, "intimacy_level", 0.0) or 0.0)
    peak = float(getattr(relationship, "peak_intimacy_level", 0.0) or 0.0)

    # Condition 1: stage regressed OR intimacy decayed > 0.1 from peak
    stage_regressed = prev_stage and _ORDER.get(prev_stage, 0) > _ORDER.get(stage, 0)
    intimacy_decayed = peak > 0 and (peak - intimacy) > 0.1
    if not stage_regressed and not intimacy_decayed:
        return False

    # Condition 2: response rate < 0.4
    metrics_rate = getattr(outreach_metrics, "response_rate", 1.0) if outreach_metrics else 1.0
    if metrics_rate >= 0.4:
        return False

    # Condition 3: last outreach >= 72 hours ago
    if last_outreach_sent_at:
        try:
            last_dt = datetime.fromisoformat(last_outreach_sent_at)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=now.tzinfo)
            hours_since = (now - last_dt).total_seconds() / 3600
            if hours_since < 72:
                return False
        except (ValueError, TypeError):
            pass

    return True


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
    *,
    client_id: str = "",
    channel_id: str = "",
    thread_id: str = "",
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
        client_id=client_id,
        now=now,
        routine_state=str(getattr(lifestyle_state, "routine_state", "") or ""),
    )
    self_context = ""
    if client_id and channel_id and thread_id:
        self_context, _ = build_companion_self_context(
            store,
            client_id=client_id,
            channel_id=channel_id,
            thread_id=thread_id,
            now=now,
            routine_state=str(getattr(lifestyle_state, "routine_state", "") or ""),
        )
    parts = [base, schedule_context]
    if self_context:
        parts.append(self_context)
    return "\n".join(part for part in parts if part)
