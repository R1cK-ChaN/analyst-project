from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from analyst.contracts import utc_now
from analyst.memory import CompanionScheduleUpdate
from analyst.storage import CompanionDailyScheduleRecord, SQLiteEngineStore

COMPANION_SCHEDULE_TIMEZONE_NAME = "Asia/Singapore"
COMPANION_SCHEDULE_TIMEZONE = ZoneInfo(COMPANION_SCHEDULE_TIMEZONE_NAME)
COMPANION_SCHEDULE_ANCHOR_FIELDS = (
    "morning_plan",
    "lunch_plan",
    "afternoon_plan",
    "dinner_plan",
    "evening_plan",
)
COMPANION_SCHEDULE_FLOW_FIELDS = (
    "current_plan",
    "next_plan",
)
_USER_DIRECTED_SCHEDULE_PATTERNS = (
    "meet",
    "meeting up",
    "catch up",
    "hang out",
    "come over",
    "see you",
    "see me",
    "pick me up",
    "pick you up",
    "change your",
    "reschedule your",
    "let's meet",
    "lets meet",
    "见面",
    "碰头",
    "约饭",
    "约一下",
    "线下",
    "来找我",
    "接我",
    "接你",
    "陪我",
    "改成",
    "改吃",
    "改一下你的",
)
_USER_REMINDER_PATTERNS = (
    "remind me",
    "set a reminder",
    "提醒我",
    "记得提醒我",
    "到时候叫我",
)


def companion_schedule_local_now(now: datetime | None = None) -> datetime:
    current = now or utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(COMPANION_SCHEDULE_TIMEZONE)


def companion_schedule_date(now: datetime | None = None) -> str:
    return companion_schedule_local_now(now).date().isoformat()


def _user_controls_companion_schedule(user_text: str) -> bool:
    lowered = str(user_text or "").casefold()
    if not lowered:
        return False
    return any(token in lowered for token in (*_USER_DIRECTED_SCHEDULE_PATTERNS, *_USER_REMINDER_PATTERNS))


def ensure_companion_daily_schedule(
    store: SQLiteEngineStore,
    *,
    client_id: str = "",
    now: datetime | None = None,
    routine_state: str = "",
) -> CompanionDailyScheduleRecord:
    local_now = companion_schedule_local_now(now)
    return store.upsert_companion_daily_schedule(
        client_id=client_id,
        schedule_date=local_now.date().isoformat(),
        timezone_name=COMPANION_SCHEDULE_TIMEZONE_NAME,
        routine_state_snapshot=routine_state or None,
    )


def build_companion_schedule_context(
    store: SQLiteEngineStore,
    *,
    client_id: str = "",
    now: datetime | None = None,
    routine_state: str = "",
) -> str:
    local_now = companion_schedule_local_now(now)
    schedule = ensure_companion_daily_schedule(
        store,
        client_id=client_id,
        now=local_now,
        routine_state=routine_state,
    )
    day_type = "weekend" if local_now.weekday() >= 5 else "weekday"
    effective_routine_state = routine_state or schedule.routine_state_snapshot
    lines = [
        f"local_date: {schedule.schedule_date}",
        f"day_type: {day_type}",
        f"schedule_timezone: {schedule.timezone_name}",
        f"routine_state: {effective_routine_state or '(unset)'}",
    ]
    for field in (*COMPANION_SCHEDULE_ANCHOR_FIELDS, *COMPANION_SCHEDULE_FLOW_FIELDS):
        value = getattr(schedule, field)
        lines.append(f"{field}: {value or '(unset)'}")
    lines.append(
        f"last_explicit_schedule_update_at: {schedule.last_explicit_update_at or '(unset)'}"
    )
    lines.append(f"revision_note: {schedule.revision_note or '(unset)'}")
    return "\n".join(lines)


def apply_companion_schedule_update(
    store: SQLiteEngineStore,
    update: CompanionScheduleUpdate,
    *,
    client_id: str = "",
    now: datetime | None = None,
    routine_state: str = "",
    user_text: str = "",
) -> CompanionDailyScheduleRecord:
    local_now = companion_schedule_local_now(now)
    schedule = ensure_companion_daily_schedule(
        store,
        client_id=client_id,
        now=local_now,
        routine_state=routine_state,
    )
    if not update.has_changes():
        return schedule
    if _user_controls_companion_schedule(user_text):
        return schedule

    updates: dict[str, str] = {}
    normalized_mode = update.normalized_revision_mode()
    for field in COMPANION_SCHEDULE_ANCHOR_FIELDS:
        value = getattr(update, field)
        if value is None:
            continue
        existing = getattr(schedule, field)
        if existing and normalized_mode != "revise":
            continue
        updates[field] = value
    for field in COMPANION_SCHEDULE_FLOW_FIELDS:
        value = getattr(update, field)
        if value is not None:
            updates[field] = value

    if routine_state:
        updates["routine_state_snapshot"] = routine_state
    if not updates:
        return schedule

    updates["last_explicit_update_at"] = utc_now().isoformat()
    if update.revision_note is not None:
        updates["revision_note"] = update.revision_note
    return store.upsert_companion_daily_schedule(
        client_id=client_id,
        schedule_date=schedule.schedule_date,
        timezone_name=COMPANION_SCHEDULE_TIMEZONE_NAME,
        **updates,
    )
