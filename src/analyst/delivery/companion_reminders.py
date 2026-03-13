from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from analyst.contracts import normalize_utc_iso, utc_now
from analyst.memory import CompanionReminderUpdate
from analyst.storage import CompanionReminderRecord, SQLiteEngineStore

COMPANION_REMINDER_TIMEZONE_NAME = "Asia/Singapore"
COMPANION_REMINDER_TIMEZONE = ZoneInfo(COMPANION_REMINDER_TIMEZONE_NAME)


def apply_companion_reminder_update(
    store: SQLiteEngineStore,
    update: CompanionReminderUpdate,
    *,
    client_id: str,
    channel_id: str,
    thread_id: str,
    now: datetime | None = None,
    preferred_language: str = "",
) -> CompanionReminderRecord | None:
    if not update.has_changes():
        return None
    due_at = _normalize_reminder_due_at(
        str(update.due_at or ""),
        timezone_name=str(update.timezone_name or COMPANION_REMINDER_TIMEZONE_NAME),
    )
    if not due_at:
        return None
    reference_now = now or utc_now()
    if reference_now.tzinfo is None:
        reference_now = reference_now.replace(tzinfo=timezone.utc)
    due_at_dt = datetime.fromisoformat(due_at).astimezone(timezone.utc)
    if due_at_dt <= reference_now.astimezone(timezone.utc):
        return None
    reminder_text = str(update.reminder_text or "").strip()
    if not reminder_text:
        return None
    return store.create_companion_reminder(
        client_id=client_id,
        channel=channel_id,
        thread_id=thread_id,
        reminder_text=reminder_text,
        due_at=due_at,
        timezone_name=str(update.timezone_name or COMPANION_REMINDER_TIMEZONE_NAME or ""),
        metadata={"preferred_language": preferred_language or _infer_reminder_language(reminder_text)},
    )


def render_companion_reminder_message(reminder: CompanionReminderRecord) -> str:
    preferred_language = str(reminder.metadata.get("preferred_language", "") or "")
    if preferred_language == "en":
        return f"Reminder: {reminder.reminder_text}"
    return f"提醒你一下：{reminder.reminder_text}"


def _normalize_reminder_due_at(raw_due_at: str, *, timezone_name: str) -> str:
    if not raw_due_at:
        return ""
    try:
        zone = ZoneInfo(timezone_name or COMPANION_REMINDER_TIMEZONE_NAME)
    except Exception:
        zone = COMPANION_REMINDER_TIMEZONE
    try:
        return normalize_utc_iso(raw_due_at, default_tz=zone)
    except ValueError:
        return ""


def _infer_reminder_language(reminder_text: str) -> str:
    return "zh" if any("\u4e00" <= ch <= "\u9fff" for ch in reminder_text) else "en"
