from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from analyst.contracts import (
    epoch_to_datetime,
    format_epoch_iso,
    format_epoch_iso_in_timezone,
    normalize_utc_iso,
    to_epoch_ms,
    utc_now,
)

from .sqlite_core import (
    _infer_timestamp_precision,
    _matches_scope_tags,
    _safe_epoch_ms,
    _safe_utc_iso,
    default_engine_db_path,
)
from .sqlite_records import (
    StoredEventRecord,
    CalendarIndicatorRecord,
    CalendarIndicatorAliasRecord,
    MarketPriceRecord,
    CentralBankCommunicationRecord,
    IndicatorObservationRecord,
    IndicatorVintageRecord,
    ObsSourceRecord,
    ObsFamilyRecord,
    ObsFamilyDocumentRecord,
    NewsArticleRecord,
    RegimeSnapshotRecord,
    GeneratedNoteRecord,
    AnalyticalObservationRecord,
    ResearchArtifactRecord,
    TradeSignalRecord,
    DecisionLogRecord,
    PositionStateRecord,
    PerformanceRecord,
    TradingArtifactRecord,
    ClientProfileRecord,
    CompanionCheckInStateRecord,
    CompanionImageLogRecord,
    CompanionLifestyleStateRecord,
    CompanionDailyScheduleRecord,
    CompanionSelfStateRecord,
    CompanionOutreachLogRecord,
    CompanionRelationshipStateRecord,
    CompanionReminderRecord,
    ConversationMessageRecord,
    DeliveryQueueRecord,
    GroupProfileRecord,
    GroupMemberRecord,
    GroupMessageRecord,
    DocSourceRecord,
    DocReleaseFamilyRecord,
    DocumentRecord,
    DocumentBlobRecord,
    DocumentExtraRecord
)
from .sqlite_seed_data import (
    _BIS_FAMILY_MAP,
    _CALENDAR_ALIAS_DEFS,
    _CALENDAR_INDICATOR_DEFS,
    _ECB_FAMILY_MAP,
    _EIA_FAMILY_MAP,
    _EUROSTAT_FAMILY_MAP,
    _FRED_FAMILY_MAP,
    _IMF_FAMILY_MAP,
    _NYFED_FAMILY_MAP,
    _OBS_DOC_LINKS,
    _OBS_SOURCE_DEFS,
    _OECD_FAMILY_MAP,
    _TREASURY_FAMILY_MAP,
    _VINTAGE_FAMILY_IDS,
    _WORLDBANK_FAMILY_MAP,
)

class SQLiteMemoryMixin:
    def get_client_profile(self, client_id: str) -> ClientProfileRecord:
        with self._connection(commit=False) as connection:
            row = connection.execute(
                """
                SELECT * FROM client_profiles
                WHERE client_id = ?
                LIMIT 1
                """,
                (client_id,),
            ).fetchone()
        return self._row_to_client_profile(row, client_id=client_id)

    def upsert_client_profile(
        self,
        client_id: str,
        *,
        preferred_language: str | None = None,
        watchlist_topics: list[str] | None = None,
        response_style: str | None = None,
        risk_appetite: str | None = None,
        investment_horizon: str | None = None,
        institution_type: str | None = None,
        risk_preference: str | None = None,
        asset_focus: list[str] | None = None,
        market_focus: list[str] | None = None,
        expertise_level: str | None = None,
        activity: str | None = None,
        current_mood: str | None = None,
        emotional_trend: str | None = None,
        stress_level: str | None = None,
        confidence: str | None = None,
        notes: str | None = None,
        personal_facts: list[str] | None = None,
        last_active_at: str | None = None,
        interaction_increment: int = 0,
        timezone_name: str | None = None,
    ) -> ClientProfileRecord:
        with self._connection(commit=True) as connection:
            return self._upsert_client_profile_in_connection(
                connection,
                client_id=client_id,
                preferred_language=preferred_language,
                watchlist_topics=watchlist_topics,
                response_style=response_style,
                risk_appetite=risk_appetite,
                investment_horizon=investment_horizon,
                institution_type=institution_type,
                risk_preference=risk_preference,
                asset_focus=asset_focus,
                market_focus=market_focus,
                expertise_level=expertise_level,
                activity=activity,
                current_mood=current_mood,
                emotional_trend=emotional_trend,
                stress_level=stress_level,
                confidence=confidence,
                notes=notes,
                personal_facts=personal_facts,
                last_active_at=last_active_at,
                interaction_increment=interaction_increment,
                timezone_name=timezone_name,
            )

    def get_companion_checkin_state(
        self,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
    ) -> CompanionCheckInStateRecord:
        with self._connection(commit=False) as connection:
            return self._get_companion_checkin_state_in_connection(
                connection,
                client_id=client_id,
                channel=channel,
                thread_id=thread_id,
            )

    def set_companion_checkins_enabled(
        self,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
        enabled: bool,
    ) -> CompanionCheckInStateRecord:
        with self._connection(commit=True) as connection:
            self._ensure_conversation_thread_in_connection(
                connection,
                client_id=client_id,
                channel=channel,
                thread_id=thread_id,
            )
            return self._upsert_companion_checkin_state_in_connection(
                connection,
                client_id=client_id,
                channel=channel,
                thread_id=thread_id,
                enabled=enabled,
                pending_kind="" if not enabled else None,
                pending_due_at="" if not enabled else None,
                retry_count=0 if not enabled else None,
            )

    def schedule_companion_checkin(
        self,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
        kind: str,
        due_at: str,
    ) -> CompanionCheckInStateRecord:
        with self._connection(commit=True) as connection:
            current = self._get_companion_checkin_state_in_connection(
                connection,
                client_id=client_id,
                channel=channel,
                thread_id=thread_id,
            )
            if not current.enabled:
                return current
            self._ensure_conversation_thread_in_connection(
                connection,
                client_id=client_id,
                channel=channel,
                thread_id=thread_id,
            )
            return self._upsert_companion_checkin_state_in_connection(
                connection,
                client_id=client_id,
                channel=channel,
                thread_id=thread_id,
                pending_kind=kind,
                pending_due_at=due_at,
                retry_count=0,
            )

    def clear_companion_checkin_pending(
        self,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
    ) -> CompanionCheckInStateRecord:
        with self._connection(commit=True) as connection:
            return self._upsert_companion_checkin_state_in_connection(
                connection,
                client_id=client_id,
                channel=channel,
                thread_id=thread_id,
                pending_kind="",
                pending_due_at="",
                retry_count=0,
            )

    def list_due_companion_checkins(
        self,
        *,
        now_iso: str,
        limit: int = 20,
    ) -> list[CompanionCheckInStateRecord]:
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT * FROM companion_checkin_state
                WHERE enabled = 1
                  AND pending_kind != ''
                  AND pending_due_at != ''
                  AND pending_due_at <= ?
                  AND (cooldown_until = '' OR cooldown_until <= ?)
                ORDER BY pending_due_at ASC
                LIMIT ?
                """,
                (now_iso, now_iso, limit),
            ).fetchall()
        return [
            self._row_to_companion_checkin_state(
                row,
                client_id=row["client_id"],
                channel=row["channel"],
                thread_id=row["thread_id"],
            )
            for row in rows
        ]

    def mark_companion_checkin_sent(
        self,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
        kind: str,
        sent_at: str,
        cooldown_until: str,
    ) -> CompanionCheckInStateRecord:
        with self._connection(commit=True) as connection:
            return self._upsert_companion_checkin_state_in_connection(
                connection,
                client_id=client_id,
                channel=channel,
                thread_id=thread_id,
                pending_kind="",
                pending_due_at="",
                last_sent_at=sent_at,
                last_sent_kind=kind,
                cooldown_until=cooldown_until,
                retry_count=0,
            )

    def reschedule_companion_checkin_retry(
        self,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
        next_due_at: str,
        retry_count: int,
    ) -> CompanionCheckInStateRecord:
        with self._connection(commit=True) as connection:
            return self._upsert_companion_checkin_state_in_connection(
                connection,
                client_id=client_id,
                channel=channel,
                thread_id=thread_id,
                pending_due_at=next_due_at,
                retry_count=retry_count,
            )

    # -- Outreach log -----------------------------------------------------------

    def log_companion_outreach(
        self,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
        kind: str,
        content_raw: str,
        sent_at: str,
    ) -> CompanionOutreachLogRecord:
        from analyst.delivery.outreach_dedup import normalize_outreach_text

        content_normalized = normalize_outreach_text(content_raw)
        now_iso = utc_now().isoformat()
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                INSERT INTO companion_outreach_log
                    (client_id, channel, thread_id, kind, content_raw, content_normalized,
                     sent_at, user_replied, user_replied_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, '', ?)
                """,
                (client_id, channel, thread_id, kind, content_raw, content_normalized, sent_at, now_iso),
            )
            row_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        return CompanionOutreachLogRecord(
            outreach_id=row_id,
            client_id=client_id,
            channel=channel,
            thread_id=thread_id,
            kind=kind,
            content_raw=content_raw,
            content_normalized=content_normalized,
            sent_at=sent_at,
            user_replied=False,
            user_replied_at="",
            created_at=now_iso,
        )

    def list_recent_companion_outreach(
        self,
        *,
        client_id: str,
        days: int = 7,
        limit: int = 50,
    ) -> list[CompanionOutreachLogRecord]:
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT * FROM companion_outreach_log
                WHERE client_id = ?
                  AND sent_at >= datetime('now', ?)
                ORDER BY sent_at DESC
                LIMIT ?
                """,
                (client_id, f"-{days} days", limit),
            ).fetchall()
        return [self._row_to_outreach_log(row) for row in rows]

    def mark_outreach_replied(
        self,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
        replied_at: str,
    ) -> None:
        """Mark the most recent unreplied outreach as replied (within 4h window).

        Uses strftime to strip timezone suffixes for reliable SQLite datetime math.
        """
        # Normalize to bare ISO format (no TZ suffix, space separator) for SQLite datetime math.
        clean_replied = replied_at.replace("+00:00", "").replace("Z", "").replace("T", " ")
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                UPDATE companion_outreach_log
                SET user_replied = 1, user_replied_at = ?
                WHERE id = (
                    SELECT id FROM companion_outreach_log
                    WHERE client_id = ? AND channel = ? AND thread_id = ?
                      AND user_replied = 0
                      AND REPLACE(REPLACE(REPLACE(sent_at, '+00:00', ''), 'Z', ''), 'T', ' ')
                          >= datetime(?, '-4 hours')
                    ORDER BY sent_at DESC
                    LIMIT 1
                )
                """,
                (replied_at, client_id, channel, thread_id, clean_replied),
            )

    def count_outreach_sent_today(
        self,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
    ) -> int:
        with self._connection(commit=False) as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) FROM companion_outreach_log
                WHERE client_id = ? AND channel = ? AND thread_id = ?
                  AND date(sent_at) = date('now')
                """,
                (client_id, channel, thread_id),
            ).fetchone()
        return int(row[0]) if row else 0

    def get_last_outreach_sent_at(
        self,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
    ) -> str | None:
        with self._connection(commit=False) as connection:
            row = connection.execute(
                """
                SELECT sent_at FROM companion_outreach_log
                WHERE client_id = ? AND channel = ? AND thread_id = ?
                ORDER BY sent_at DESC
                LIMIT 1
                """,
                (client_id, channel, thread_id),
            ).fetchone()
        return str(row[0]) if row else None

    def _row_to_outreach_log(self, row: sqlite3.Row) -> CompanionOutreachLogRecord:
        return CompanionOutreachLogRecord(
            outreach_id=int(row["id"]),
            client_id=row["client_id"],
            channel=row["channel"],
            thread_id=row["thread_id"],
            kind=row["kind"],
            content_raw=row["content_raw"],
            content_normalized=row["content_normalized"],
            sent_at=row["sent_at"],
            user_replied=bool(row["user_replied"]),
            user_replied_at=row["user_replied_at"],
            created_at=row["created_at"],
        )

    # -- Image log -------------------------------------------------------------

    def log_companion_image(
        self,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
        mode: str,
        scene_key: str = "",
        trigger_type: str,
        outreach_kind: str = "",
        relationship_stage: str,
        generated_at: str,
        scene_override: bool = False,
        blocked: bool = False,
        block_reason: str = "",
    ) -> CompanionImageLogRecord:
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                INSERT INTO companion_image_log
                    (client_id, channel, thread_id, mode, scene_key, trigger_type,
                     outreach_kind, relationship_stage, generated_at, scene_override,
                     blocked, block_reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    client_id, channel, thread_id, mode, scene_key, trigger_type,
                    outreach_kind, relationship_stage, generated_at,
                    int(scene_override), int(blocked), block_reason,
                ),
            )
            row_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        return CompanionImageLogRecord(
            image_log_id=row_id,
            client_id=client_id,
            channel=channel,
            thread_id=thread_id,
            mode=mode,
            scene_key=scene_key,
            trigger_type=trigger_type,
            outreach_kind=outreach_kind,
            relationship_stage=relationship_stage,
            generated_at=generated_at,
            scene_override=scene_override,
            blocked=blocked,
            block_reason=block_reason,
        )

    def count_images_sent_today(
        self,
        *,
        client_id: str,
        timezone_name: str = "UTC",
    ) -> int:
        """Count non-blocked images sent today in user's local time."""
        with self._connection(commit=False) as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) FROM companion_image_log
                WHERE client_id = ?
                  AND blocked = 0
                  AND date(generated_at) = date('now')
                """,
                (client_id,),
            ).fetchone()
        return int(row[0]) if row else 0

    def count_proactive_images_today(
        self,
        *,
        client_id: str,
        timezone_name: str = "UTC",
    ) -> int:
        """Count non-blocked proactive images sent today."""
        with self._connection(commit=False) as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) FROM companion_image_log
                WHERE client_id = ?
                  AND blocked = 0
                  AND trigger_type = 'proactive'
                  AND date(generated_at) = date('now')
                """,
                (client_id,),
            ).fetchone()
        return int(row[0]) if row else 0

    def count_warmup_images_last_5_days(
        self,
        *,
        client_id: str,
    ) -> int:
        """Count non-blocked warm_up_share images in the last 5 days."""
        with self._connection(commit=False) as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) FROM companion_image_log
                WHERE client_id = ?
                  AND blocked = 0
                  AND outreach_kind = 'warm_up_share'
                  AND generated_at >= datetime('now', '-5 days')
                """,
                (client_id,),
            ).fetchone()
        return int(row[0]) if row else 0

    def get_turns_since_last_image(
        self,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
    ) -> int:
        """Count conversation messages since last non-blocked image log entry."""
        with self._connection(commit=False) as connection:
            # Find the most recent non-blocked image generation time
            last_image_row = connection.execute(
                """
                SELECT generated_at FROM companion_image_log
                WHERE client_id = ? AND channel = ? AND thread_id = ?
                  AND blocked = 0
                ORDER BY generated_at DESC
                LIMIT 1
                """,
                (client_id, channel, thread_id),
            ).fetchone()
            if last_image_row is None:
                return 999  # No prior images — effectively unlimited
            last_image_at = last_image_row[0]
            # Count messages since that time
            count_row = connection.execute(
                """
                SELECT COUNT(*) FROM conversation_messages
                WHERE client_id = ? AND channel = ? AND thread_id = ?
                  AND created_at > ?
                """,
                (client_id, channel, thread_id, last_image_at),
            ).fetchone()
        return int(count_row[0]) if count_row else 999

    def _row_to_image_log(self, row: sqlite3.Row) -> CompanionImageLogRecord:
        return CompanionImageLogRecord(
            image_log_id=int(row["id"]),
            client_id=row["client_id"],
            channel=row["channel"],
            thread_id=row["thread_id"],
            mode=row["mode"],
            scene_key=row["scene_key"],
            trigger_type=row["trigger_type"],
            outreach_kind=row["outreach_kind"],
            relationship_stage=row["relationship_stage"],
            generated_at=row["generated_at"],
            scene_override=bool(row["scene_override"]),
            blocked=bool(row["blocked"]),
            block_reason=row["block_reason"],
        )

    # -- Lifestyle state -------------------------------------------------------

    def get_companion_lifestyle_state(
        self,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
    ) -> CompanionLifestyleStateRecord:
        with self._connection(commit=False) as connection:
            return self._get_companion_lifestyle_state_in_connection(
                connection,
                client_id=client_id,
                channel=channel,
                thread_id=thread_id,
            )

    def upsert_companion_lifestyle_state(
        self,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
        timezone_name: str | None = None,
        home_base: str | None = None,
        work_area: str | None = None,
        routine_state: str | None = None,
        last_state_changed_at: str | None = None,
    ) -> CompanionLifestyleStateRecord:
        with self._connection(commit=True) as connection:
            self._ensure_conversation_thread_in_connection(
                connection,
                client_id=client_id,
                channel=channel,
                thread_id=thread_id,
            )
            return self._upsert_companion_lifestyle_state_in_connection(
                connection,
                client_id=client_id,
                channel=channel,
                thread_id=thread_id,
                timezone_name=timezone_name,
                home_base=home_base,
                work_area=work_area,
                routine_state=routine_state,
                last_state_changed_at=last_state_changed_at,
            )

    def mark_companion_lifestyle_ping_sent(
        self,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
        kind: str,
        sent_at: str,
    ) -> CompanionLifestyleStateRecord:
        updates: dict[str, str] = {}
        normalized = str(kind).strip().lower()
        if normalized == "morning":
            updates["last_morning_checkin_at"] = sent_at
        elif normalized == "evening":
            updates["last_evening_checkin_at"] = sent_at
        elif normalized == "weekend":
            updates["last_weekend_checkin_at"] = sent_at
        with self._connection(commit=True) as connection:
            return self._upsert_companion_lifestyle_state_in_connection(
                connection,
                client_id=client_id,
                channel=channel,
                thread_id=thread_id,
                **updates,
            )

    def list_enabled_companion_checkins(
        self,
        *,
        channel_prefix: str = "telegram:",
        limit: int = 200,
    ) -> list[CompanionCheckInStateRecord]:
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT * FROM companion_checkin_state
                WHERE enabled = 1 AND channel LIKE ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (f"{channel_prefix}%", limit),
            ).fetchall()
        return [
            self._row_to_companion_checkin_state(
                row,
                client_id=row["client_id"],
                channel=row["channel"],
                thread_id=row["thread_id"],
            )
            for row in rows
        ]

    def get_companion_daily_schedule(
        self,
        *,
        client_id: str = "",
        schedule_date: str,
        timezone_name: str = "Asia/Singapore",
    ) -> CompanionDailyScheduleRecord:
        with self._connection(commit=False) as connection:
            return self._get_companion_daily_schedule_in_connection(
                connection,
                client_id=client_id,
                schedule_date=schedule_date,
                timezone_name=timezone_name,
            )

    def upsert_companion_daily_schedule(
        self,
        *,
        client_id: str = "",
        schedule_date: str,
        timezone_name: str | None = None,
        routine_state_snapshot: str | None = None,
        morning_plan: str | None = None,
        lunch_plan: str | None = None,
        afternoon_plan: str | None = None,
        dinner_plan: str | None = None,
        evening_plan: str | None = None,
        current_plan: str | None = None,
        next_plan: str | None = None,
        revision_note: str | None = None,
        last_explicit_update_at: str | None = None,
    ) -> CompanionDailyScheduleRecord:
        with self._connection(commit=True) as connection:
            return self._upsert_companion_daily_schedule_in_connection(
                connection,
                client_id=client_id,
                schedule_date=schedule_date,
                timezone_name=timezone_name,
                routine_state_snapshot=routine_state_snapshot,
                morning_plan=morning_plan,
                lunch_plan=lunch_plan,
                afternoon_plan=afternoon_plan,
                dinner_plan=dinner_plan,
                evening_plan=evening_plan,
                current_plan=current_plan,
                next_plan=next_plan,
                revision_note=revision_note,
                last_explicit_update_at=last_explicit_update_at,
            )

    def get_companion_self_state(
        self,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
        state_date: str,
        timezone_name: str = "Asia/Singapore",
    ) -> CompanionSelfStateRecord:
        with self._connection(commit=False) as connection:
            return self._get_companion_self_state_in_connection(
                connection,
                client_id=client_id,
                channel=channel,
                thread_id=thread_id,
                state_date=state_date,
                timezone_name=timezone_name,
            )

    def upsert_companion_self_state(
        self,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
        state_date: str,
        timezone_name: str | None = None,
        routine_state_snapshot: str | None = None,
        internal_state: list[str] | None = None,
        opinion_profile: list[str] | None = None,
        used_callback_facts: list[str] | None = None,
        last_callback_fact: str | None = None,
        last_callback_at: str | None = None,
        last_engagement_mode: str | None = None,
        last_engagement_reason: str | None = None,
    ) -> CompanionSelfStateRecord:
        with self._connection(commit=True) as connection:
            self._ensure_conversation_thread_in_connection(
                connection,
                client_id=client_id,
                channel=channel,
                thread_id=thread_id,
            )
            return self._upsert_companion_self_state_in_connection(
                connection,
                client_id=client_id,
                channel=channel,
                thread_id=thread_id,
                state_date=state_date,
                timezone_name=timezone_name,
                routine_state_snapshot=routine_state_snapshot,
                internal_state=internal_state,
                opinion_profile=opinion_profile,
                used_callback_facts=used_callback_facts,
                last_callback_fact=last_callback_fact,
                last_callback_at=last_callback_at,
                last_engagement_mode=last_engagement_mode,
                last_engagement_reason=last_engagement_reason,
            )

    def get_companion_relationship_state(
        self, *, client_id: str
    ) -> CompanionRelationshipStateRecord:
        with self._connection(commit=False) as connection:
            return self._get_companion_relationship_state_in_connection(
                connection, client_id=client_id
            )

    def update_companion_relationship_state(
        self,
        *,
        client_id: str,
        intimacy_level: float | None = None,
        relationship_stage: str | None = None,
        tendency_friend: float | None = None,
        tendency_romantic: float | None = None,
        tendency_confidant: float | None = None,
        tendency_mentor: float | None = None,
        streak_days: int | None = None,
        total_turns: int | None = None,
        avg_session_turns: float | None = None,
        mood_history: list[str] | None = None,
        nicknames: list[dict] | None = None,
        previous_stage: str | None = None,
        last_interaction_date: str | None = None,
        last_stage_transition_at: str | None = None,
        emotional_trend: str | None = None,
        outreach_paused: bool | None = None,
        outreach_paused_at: str | None = None,
        peak_intimacy_level: float | None = None,
        tendency_damping_json: str | None = None,
    ) -> CompanionRelationshipStateRecord:
        with self._connection(commit=True) as connection:
            return self._upsert_companion_relationship_state_in_connection(
                connection,
                client_id=client_id,
                intimacy_level=intimacy_level,
                relationship_stage=relationship_stage,
                tendency_friend=tendency_friend,
                tendency_romantic=tendency_romantic,
                tendency_confidant=tendency_confidant,
                tendency_mentor=tendency_mentor,
                streak_days=streak_days,
                total_turns=total_turns,
                avg_session_turns=avg_session_turns,
                mood_history=mood_history,
                nicknames=nicknames,
                previous_stage=previous_stage,
                last_interaction_date=last_interaction_date,
                last_stage_transition_at=last_stage_transition_at,
                emotional_trend=emotional_trend,
                outreach_paused=outreach_paused,
                outreach_paused_at=outreach_paused_at,
                peak_intimacy_level=peak_intimacy_level,
                tendency_damping_json=tendency_damping_json,
            )

    def create_companion_reminder(
        self,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
        reminder_text: str,
        due_at: str,
        timezone_name: str = "Asia/Singapore",
        metadata: dict[str, Any] | None = None,
    ) -> CompanionReminderRecord:
        created_at = utc_now().isoformat()
        with self._connection(commit=True) as connection:
            self._ensure_conversation_thread_in_connection(
                connection,
                client_id=client_id,
                channel=channel,
                thread_id=thread_id,
                timestamp=created_at,
            )
            cursor = connection.execute(
                """
                INSERT INTO companion_reminders (
                    client_id,
                    channel,
                    thread_id,
                    reminder_text,
                    due_at,
                    timezone_name,
                    status,
                    sent_at,
                    metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', '', ?, ?)
                """,
                (
                    client_id,
                    channel,
                    thread_id,
                    reminder_text,
                    due_at,
                    timezone_name,
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                    created_at,
                ),
            )
            reminder_id = int(cursor.lastrowid)
        return CompanionReminderRecord(
            reminder_id=reminder_id,
            client_id=client_id,
            channel=channel,
            thread_id=thread_id,
            reminder_text=reminder_text,
            due_at=due_at,
            timezone_name=timezone_name,
            status="pending",
            created_at=created_at,
            sent_at="",
            metadata=metadata or {},
        )

    def list_due_companion_reminders(
        self,
        *,
        now_iso: str,
        limit: int = 20,
    ) -> list[CompanionReminderRecord]:
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT * FROM companion_reminders
                WHERE status = 'pending'
                  AND due_at <= ?
                ORDER BY due_at ASC, id ASC
                LIMIT ?
                """,
                (now_iso, limit),
            ).fetchall()
        return [self._row_to_companion_reminder(row) for row in rows]

    def mark_companion_reminder_sent(
        self,
        *,
        reminder_id: int,
        sent_at: str,
    ) -> CompanionReminderRecord | None:
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                UPDATE companion_reminders
                SET status = 'sent', sent_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (sent_at, reminder_id),
            )
            row = connection.execute(
                "SELECT * FROM companion_reminders WHERE id = ? LIMIT 1",
                (reminder_id,),
            ).fetchone()
        return self._row_to_companion_reminder(row) if row is not None else None

    def list_companion_reminders(
        self,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
        status: str = "",
        limit: int = 20,
    ) -> list[CompanionReminderRecord]:
        query = """
            SELECT * FROM companion_reminders
            WHERE client_id = ? AND channel = ? AND thread_id = ?
        """
        params: list[Any] = [client_id, channel, thread_id]
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._connection(commit=False) as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [self._row_to_companion_reminder(row) for row in rows]

    def get_last_user_message_at(
        self,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
    ) -> str:
        with self._connection(commit=False) as connection:
            row = connection.execute(
                """
                SELECT created_at FROM conversation_messages
                WHERE client_id = ? AND channel = ? AND thread_id = ? AND role = 'user'
                ORDER BY id DESC
                LIMIT 1
                """,
                (client_id, channel, thread_id),
            ).fetchone()
        if row is None:
            return ""
        return str(row["created_at"] or "")

    def list_recent_message_timestamps(
        self,
        *,
        client_id: str,
        limit: int = 50,
    ) -> list[str]:
        """Return created_at timestamps for recent user messages across all channels."""
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT created_at FROM conversation_messages
                WHERE client_id = ? AND role = 'user'
                ORDER BY id DESC
                LIMIT ?
                """,
                (client_id, limit),
            ).fetchall()
        return [str(row["created_at"] or "") for row in rows if row["created_at"]]

    def ensure_conversation_thread(self, *, client_id: str, channel: str, thread_id: str) -> None:
        with self._connection(commit=True) as connection:
            self._ensure_conversation_thread_in_connection(
                connection,
                client_id=client_id,
                channel=channel,
                thread_id=thread_id,
            )

    def append_conversation_message(
        self,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> ConversationMessageRecord:
        created_at = utc_now().isoformat()
        with self._connection(commit=True) as connection:
            self._ensure_conversation_thread_in_connection(
                connection,
                client_id=client_id,
                channel=channel,
                thread_id=thread_id,
                timestamp=created_at,
            )
            cursor = connection.execute(
                """
                INSERT INTO conversation_messages (
                    client_id,
                    channel,
                    thread_id,
                    role,
                    content,
                    metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    client_id,
                    channel,
                    thread_id,
                    role,
                    content,
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                    created_at,
                ),
            )
            message_id = int(cursor.lastrowid)
            connection.execute(
                """
                UPDATE conversation_threads
                SET last_active_at = ?
                WHERE client_id = ? AND channel = ? AND thread_id = ?
                """,
                (created_at, client_id, channel, thread_id),
            )
        return ConversationMessageRecord(
            message_id=message_id,
            client_id=client_id,
            channel=channel,
            thread_id=thread_id,
            role=role,
            content=content,
            created_at=created_at,
            metadata=metadata or {},
        )

    def list_conversation_messages(
        self,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
        limit: int = 12,
    ) -> list[ConversationMessageRecord]:
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT * FROM conversation_messages
                WHERE client_id = ? AND channel = ? AND thread_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (client_id, channel, thread_id, limit),
            ).fetchall()
        records = [
            ConversationMessageRecord(
                message_id=int(row["id"]),
                client_id=row["client_id"],
                channel=row["channel"],
                thread_id=row["thread_id"],
                role=row["role"],
                content=row["content"],
                created_at=row["created_at"],
                metadata=json.loads(row["metadata_json"]),
            )
            for row in rows
        ]
        records.reverse()
        return records

    def enqueue_delivery(
        self,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
        source_type: str,
        content_rendered: str,
        source_artifact_id: int | None = None,
        status: str = "delivered",
        delivered_at: str | None = None,
        client_reaction: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> DeliveryQueueRecord:
        created_at = utc_now().isoformat()
        with self._connection(commit=True) as connection:
            self._ensure_conversation_thread_in_connection(
                connection,
                client_id=client_id,
                channel=channel,
                thread_id=thread_id,
                timestamp=created_at,
            )
            cursor = connection.execute(
                """
                INSERT INTO delivery_queue (
                    client_id,
                    channel,
                    thread_id,
                    source_type,
                    source_artifact_id,
                    content_rendered,
                    status,
                    delivered_at,
                    client_reaction,
                    metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    client_id,
                    channel,
                    thread_id,
                    source_type,
                    source_artifact_id,
                    content_rendered,
                    status,
                    delivered_at,
                    client_reaction,
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                    created_at,
                ),
            )
            delivery_id = int(cursor.lastrowid)
        return DeliveryQueueRecord(
            delivery_id=delivery_id,
            client_id=client_id,
            channel=channel,
            thread_id=thread_id,
            source_type=source_type,
            source_artifact_id=source_artifact_id,
            content_rendered=content_rendered,
            status=status,
            delivered_at=delivered_at,
            client_reaction=client_reaction,
            created_at=created_at,
            metadata=metadata or {},
        )

    def list_recent_deliveries(
        self,
        *,
        client_id: str,
        channel: str | None = None,
        thread_id: str | None = None,
        limit: int = 5,
    ) -> list[DeliveryQueueRecord]:
        conditions = ["client_id = ?"]
        params: list[Any] = [client_id]
        if channel is not None:
            conditions.append("channel = ?")
            params.append(channel)
        if thread_id is not None:
            conditions.append("thread_id = ?")
            params.append(thread_id)
        params.append(limit)
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM delivery_queue
                WHERE {' AND '.join(conditions)}
                ORDER BY id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            DeliveryQueueRecord(
                delivery_id=int(row["id"]),
                client_id=row["client_id"],
                channel=row["channel"],
                thread_id=row["thread_id"],
                source_type=row["source_type"],
                source_artifact_id=int(row["source_artifact_id"]) if row["source_artifact_id"] is not None else None,
                content_rendered=row["content_rendered"],
                status=row["status"],
                delivered_at=row["delivered_at"],
                client_reaction=row["client_reaction"],
                created_at=row["created_at"],
                metadata=json.loads(row["metadata_json"]),
            )
            for row in rows
        ]

    @staticmethod
    def _recency_decay(created_at: str, *, half_life_hours: float = 24.0) -> float:
        """Exponential decay factor: 1.0 for now, 0.5 at half_life_hours ago, etc."""
        try:
            created = datetime.fromisoformat(created_at)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_hours = max((utc_now() - created).total_seconds() / 3600.0, 0.0)
            return math.pow(0.5, age_hours / half_life_hours)
        except (ValueError, TypeError):
            return 0.5

    def search_delivery_queue(
        self,
        *,
        client_id: str,
        query: str,
        channel: str | None = None,
        thread_id: str | None = None,
        limit: int = 3,
    ) -> list[DeliveryQueueRecord]:
        terms = self._search_terms(query)
        candidates = self.list_recent_deliveries(
            client_id=client_id,
            channel=channel,
            thread_id=thread_id,
            limit=max(limit * 12, 50),
        )
        scored: list[tuple[float, DeliveryQueueRecord]] = []
        for item in candidates:
            score = self._score_text_match(item.content_rendered, terms)
            if score <= 0:
                continue
            score *= self._recency_decay(item.created_at)
            scored.append((score, item))
        scored.sort(key=lambda pair: (pair[0], pair[1].created_at), reverse=True)
        return [record for _, record in scored[:limit]]

    def record_user_interaction(
        self,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
        user_text: str,
        assistant_text: str,
        tool_audit: list[dict[str, Any]],
        profile_updates: dict[str, Any],
    ) -> None:
        user_timestamp = utc_now().isoformat()
        assistant_timestamp = utc_now().isoformat()
        with self._connection(commit=True) as connection:
            self._upsert_client_profile_in_connection(
                connection,
                client_id=client_id,
                preferred_language=profile_updates.get("preferred_language"),
                watchlist_topics=profile_updates.get("watchlist_topics"),
                response_style=profile_updates.get("response_style"),
                risk_appetite=profile_updates.get("risk_appetite"),
                investment_horizon=profile_updates.get("investment_horizon"),
                institution_type=profile_updates.get("institution_type"),
                risk_preference=profile_updates.get("risk_preference"),
                asset_focus=profile_updates.get("asset_focus"),
                market_focus=profile_updates.get("market_focus"),
                expertise_level=profile_updates.get("expertise_level"),
                activity=profile_updates.get("activity"),
                current_mood=profile_updates.get("current_mood"),
                emotional_trend=profile_updates.get("emotional_trend"),
                stress_level=profile_updates.get("stress_level"),
                confidence=profile_updates.get("confidence"),
                notes=profile_updates.get("notes"),
                personal_facts=profile_updates.get("personal_facts"),
                last_active_at=assistant_timestamp,
                interaction_increment=1,
                timezone_name=profile_updates.get("timezone_name"),
            )
            self._ensure_conversation_thread_in_connection(
                connection,
                client_id=client_id,
                channel=channel,
                thread_id=thread_id,
                timestamp=assistant_timestamp,
            )
            connection.executemany(
                """
                INSERT INTO conversation_messages (
                    client_id,
                    channel,
                    thread_id,
                    role,
                    content,
                    metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        client_id,
                        channel,
                        thread_id,
                        "user",
                        user_text,
                        json.dumps({"channel": channel}, ensure_ascii=False, sort_keys=True),
                        user_timestamp,
                    ),
                    (
                        client_id,
                        channel,
                        thread_id,
                        "assistant",
                        assistant_text,
                        json.dumps(
                            {"channel": channel, "tool_audit": tool_audit},
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        assistant_timestamp,
                    ),
                ],
            )
            connection.execute(
                """
                INSERT INTO delivery_queue (
                    client_id,
                    channel,
                    thread_id,
                    source_type,
                    source_artifact_id,
                    content_rendered,
                    status,
                    delivered_at,
                    client_reaction,
                    metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    client_id,
                    channel,
                    thread_id,
                    "user_reply",
                    None,
                    assistant_text,
                    "delivered",
                    assistant_timestamp,
                    "",
                    json.dumps(
                        {"user_text": user_text, "tool_audit": tool_audit},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    assistant_timestamp,
                ),
            )

    def _row_to_client_profile(self, row: sqlite3.Row | None, *, client_id: str) -> ClientProfileRecord:
        if row is None:
            return ClientProfileRecord(
                client_id=client_id,
                preferred_language="",
                watchlist_topics=[],
                response_style="",
                risk_appetite="",
                investment_horizon="",
                institution_type="",
                risk_preference="",
                asset_focus=[],
                market_focus=[],
                expertise_level="",
                activity="",
                current_mood="",
                emotional_trend="",
                stress_level="",
                confidence="",
                notes="",
                personal_facts=[],
                last_active_at="",
                total_interactions=0,
                updated_at="",
                timezone_name="Asia/Shanghai",
            )
        return ClientProfileRecord(
            client_id=row["client_id"],
            preferred_language=row["preferred_language"],
            watchlist_topics=json.loads(row["watchlist_topics_json"]),
            response_style=row["response_style"],
            risk_appetite=row["risk_appetite"],
            investment_horizon=row["investment_horizon"],
            institution_type=row["institution_type"],
            risk_preference=row["risk_preference"],
            asset_focus=json.loads(row["asset_focus_json"]),
            market_focus=json.loads(row["market_focus_json"]),
            expertise_level=row["expertise_level"],
            activity=row["activity"],
            current_mood=row["current_mood"],
            emotional_trend=row["emotional_trend"],
            stress_level=row["stress_level"],
            confidence=row["confidence"],
            notes=row["notes"],
            personal_facts=json.loads(row["personal_facts_json"]),
            last_active_at=row["last_active_at"],
            total_interactions=int(row["total_interactions"]),
            updated_at=row["updated_at"],
            timezone_name=row["timezone_name"],
        )

    def _row_to_companion_checkin_state(
        self,
        row: sqlite3.Row | None,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
    ) -> CompanionCheckInStateRecord:
        if row is None:
            return CompanionCheckInStateRecord(
                client_id=client_id,
                channel=channel,
                thread_id=thread_id,
                enabled=False,
                pending_kind="",
                pending_due_at="",
                last_sent_at="",
                last_sent_kind="",
                cooldown_until="",
                retry_count=0,
                updated_at="",
            )
        return CompanionCheckInStateRecord(
            client_id=row["client_id"],
            channel=row["channel"],
            thread_id=row["thread_id"],
            enabled=bool(row["enabled"]),
            pending_kind=row["pending_kind"],
            pending_due_at=row["pending_due_at"],
            last_sent_at=row["last_sent_at"],
            last_sent_kind=row["last_sent_kind"],
            cooldown_until=row["cooldown_until"],
            retry_count=int(row["retry_count"]),
            updated_at=row["updated_at"],
        )

    def _get_companion_checkin_state_in_connection(
        self,
        connection: sqlite3.Connection,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
    ) -> CompanionCheckInStateRecord:
        row = connection.execute(
            """
            SELECT * FROM companion_checkin_state
            WHERE client_id = ? AND channel = ? AND thread_id = ?
            LIMIT 1
            """,
            (client_id, channel, thread_id),
        ).fetchone()
        return self._row_to_companion_checkin_state(
            row,
            client_id=client_id,
            channel=channel,
            thread_id=thread_id,
        )

    def _upsert_companion_checkin_state_in_connection(
        self,
        connection: sqlite3.Connection,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
        enabled: bool | None = None,
        pending_kind: str | None = None,
        pending_due_at: str | None = None,
        last_sent_at: str | None = None,
        last_sent_kind: str | None = None,
        cooldown_until: str | None = None,
        retry_count: int | None = None,
    ) -> CompanionCheckInStateRecord:
        current = self._get_companion_checkin_state_in_connection(
            connection,
            client_id=client_id,
            channel=channel,
            thread_id=thread_id,
        )
        now_iso = utc_now().isoformat()
        next_record = CompanionCheckInStateRecord(
            client_id=client_id,
            channel=channel,
            thread_id=thread_id,
            enabled=current.enabled if enabled is None else enabled,
            pending_kind=current.pending_kind if pending_kind is None else pending_kind,
            pending_due_at=current.pending_due_at if pending_due_at is None else pending_due_at,
            last_sent_at=current.last_sent_at if last_sent_at is None else last_sent_at,
            last_sent_kind=current.last_sent_kind if last_sent_kind is None else last_sent_kind,
            cooldown_until=current.cooldown_until if cooldown_until is None else cooldown_until,
            retry_count=current.retry_count if retry_count is None else retry_count,
            updated_at=now_iso,
        )
        connection.execute(
            """
            INSERT INTO companion_checkin_state (
                client_id,
                channel,
                thread_id,
                enabled,
                pending_kind,
                pending_due_at,
                last_sent_at,
                last_sent_kind,
                cooldown_until,
                retry_count,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(client_id, channel, thread_id) DO UPDATE SET
                enabled = excluded.enabled,
                pending_kind = excluded.pending_kind,
                pending_due_at = excluded.pending_due_at,
                last_sent_at = excluded.last_sent_at,
                last_sent_kind = excluded.last_sent_kind,
                cooldown_until = excluded.cooldown_until,
                retry_count = excluded.retry_count,
                updated_at = excluded.updated_at
            """,
            (
                next_record.client_id,
                next_record.channel,
                next_record.thread_id,
                1 if next_record.enabled else 0,
                next_record.pending_kind,
                next_record.pending_due_at,
                next_record.last_sent_at,
                next_record.last_sent_kind,
                next_record.cooldown_until,
                next_record.retry_count,
                next_record.updated_at,
            ),
        )
        return next_record

    # -- Companion relationship state ------------------------------------------

    def _row_to_companion_relationship_state(
        self, row: sqlite3.Row | None, *, client_id: str
    ) -> CompanionRelationshipStateRecord:
        now_iso = utc_now().isoformat()
        if row is None:
            return CompanionRelationshipStateRecord(
                client_id=client_id,
                intimacy_level=0.0,
                relationship_stage="stranger",
                tendency_friend=0.25,
                tendency_romantic=0.25,
                tendency_confidant=0.25,
                tendency_mentor=0.25,
                streak_days=0,
                total_turns=0,
                avg_session_turns=0.0,
                mood_history=[],
                nicknames=[],
                previous_stage="",
                last_interaction_date="",
                last_stage_transition_at="",
                created_at="",
                updated_at="",
            )
        return CompanionRelationshipStateRecord(
            client_id=row["client_id"],
            intimacy_level=float(row["intimacy_level"]),
            relationship_stage=row["relationship_stage"],
            tendency_friend=float(row["tendency_friend"]),
            tendency_romantic=float(row["tendency_romantic"]),
            tendency_confidant=float(row["tendency_confidant"]),
            tendency_mentor=float(row["tendency_mentor"]),
            streak_days=int(row["streak_days"]),
            total_turns=int(row["total_turns"]),
            avg_session_turns=float(row["avg_session_turns"]),
            mood_history=json.loads(row["mood_history_json"]),
            nicknames=json.loads(row["nicknames_json"]),
            previous_stage=row["previous_stage"],
            last_interaction_date=row["last_interaction_date"],
            last_stage_transition_at=row["last_stage_transition_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            outreach_paused=bool(row["outreach_paused"]),
            outreach_paused_at=row["outreach_paused_at"],
            peak_intimacy_level=float(row["peak_intimacy_level"]),
            tendency_damping_json=row["tendency_damping_json"],
        )

    def _get_companion_relationship_state_in_connection(
        self, connection: sqlite3.Connection, *, client_id: str
    ) -> CompanionRelationshipStateRecord:
        row = connection.execute(
            "SELECT * FROM companion_relationship_state WHERE client_id = ?",
            (client_id,),
        ).fetchone()
        return self._row_to_companion_relationship_state(row, client_id=client_id)

    def _upsert_companion_relationship_state_in_connection(
        self,
        connection: sqlite3.Connection,
        *,
        client_id: str,
        intimacy_level: float | None = None,
        relationship_stage: str | None = None,
        tendency_friend: float | None = None,
        tendency_romantic: float | None = None,
        tendency_confidant: float | None = None,
        tendency_mentor: float | None = None,
        streak_days: int | None = None,
        total_turns: int | None = None,
        avg_session_turns: float | None = None,
        mood_history: list[str] | None = None,
        nicknames: list[dict] | None = None,
        previous_stage: str | None = None,
        last_interaction_date: str | None = None,
        last_stage_transition_at: str | None = None,
        emotional_trend: str | None = None,
        outreach_paused: bool | None = None,
        outreach_paused_at: str | None = None,
        peak_intimacy_level: float | None = None,
        tendency_damping_json: str | None = None,
    ) -> CompanionRelationshipStateRecord:
        current = self._get_companion_relationship_state_in_connection(connection, client_id=client_id)
        now_iso = utc_now().isoformat()
        created_at = current.created_at or now_iso

        next_intimacy = intimacy_level if intimacy_level is not None else current.intimacy_level
        next_stage = relationship_stage if relationship_stage is not None else current.relationship_stage
        next_tf = tendency_friend if tendency_friend is not None else current.tendency_friend
        next_tr = tendency_romantic if tendency_romantic is not None else current.tendency_romantic
        next_tc = tendency_confidant if tendency_confidant is not None else current.tendency_confidant
        next_tm = tendency_mentor if tendency_mentor is not None else current.tendency_mentor
        next_streak = streak_days if streak_days is not None else current.streak_days
        next_turns = total_turns if total_turns is not None else current.total_turns
        next_avg = avg_session_turns if avg_session_turns is not None else current.avg_session_turns
        next_mood_history = mood_history if mood_history is not None else current.mood_history
        next_nicknames = nicknames if nicknames is not None else current.nicknames
        next_prev_stage = previous_stage if previous_stage is not None else current.previous_stage
        next_lid = last_interaction_date if last_interaction_date is not None else current.last_interaction_date
        next_lst = last_stage_transition_at if last_stage_transition_at is not None else current.last_stage_transition_at
        next_outreach_paused = outreach_paused if outreach_paused is not None else current.outreach_paused
        next_outreach_paused_at = outreach_paused_at if outreach_paused_at is not None else current.outreach_paused_at
        next_peak = peak_intimacy_level if peak_intimacy_level is not None else current.peak_intimacy_level
        next_damping = tendency_damping_json if tendency_damping_json is not None else current.tendency_damping_json

        connection.execute(
            """
            INSERT INTO companion_relationship_state (
                client_id, intimacy_level, relationship_stage,
                tendency_friend, tendency_romantic, tendency_confidant, tendency_mentor,
                streak_days, total_turns, avg_session_turns,
                mood_history_json, nicknames_json, previous_stage,
                last_interaction_date, last_stage_transition_at,
                outreach_paused, outreach_paused_at,
                peak_intimacy_level, tendency_damping_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(client_id) DO UPDATE SET
                intimacy_level = excluded.intimacy_level,
                relationship_stage = excluded.relationship_stage,
                tendency_friend = excluded.tendency_friend,
                tendency_romantic = excluded.tendency_romantic,
                tendency_confidant = excluded.tendency_confidant,
                tendency_mentor = excluded.tendency_mentor,
                streak_days = excluded.streak_days,
                total_turns = excluded.total_turns,
                avg_session_turns = excluded.avg_session_turns,
                mood_history_json = excluded.mood_history_json,
                nicknames_json = excluded.nicknames_json,
                previous_stage = excluded.previous_stage,
                last_interaction_date = excluded.last_interaction_date,
                last_stage_transition_at = excluded.last_stage_transition_at,
                outreach_paused = excluded.outreach_paused,
                outreach_paused_at = excluded.outreach_paused_at,
                peak_intimacy_level = excluded.peak_intimacy_level,
                tendency_damping_json = excluded.tendency_damping_json,
                updated_at = excluded.updated_at
            """,
            (
                client_id,
                next_intimacy,
                next_stage,
                next_tf,
                next_tr,
                next_tc,
                next_tm,
                next_streak,
                next_turns,
                next_avg,
                json.dumps(next_mood_history, ensure_ascii=False),
                json.dumps(next_nicknames, ensure_ascii=False),
                next_prev_stage,
                next_lid,
                next_lst,
                int(next_outreach_paused),
                next_outreach_paused_at,
                next_peak,
                next_damping,
                created_at,
                now_iso,
            ),
        )
        return CompanionRelationshipStateRecord(
            client_id=client_id,
            intimacy_level=next_intimacy,
            relationship_stage=next_stage,
            tendency_friend=next_tf,
            tendency_romantic=next_tr,
            tendency_confidant=next_tc,
            tendency_mentor=next_tm,
            streak_days=next_streak,
            total_turns=next_turns,
            avg_session_turns=next_avg,
            mood_history=next_mood_history,
            nicknames=next_nicknames,
            previous_stage=next_prev_stage,
            last_interaction_date=next_lid,
            last_stage_transition_at=next_lst,
            created_at=created_at,
            updated_at=now_iso,
            outreach_paused=next_outreach_paused,
            outreach_paused_at=next_outreach_paused_at,
            peak_intimacy_level=next_peak,
            tendency_damping_json=next_damping,
        )

    def _row_to_companion_lifestyle_state(
        self,
        row: sqlite3.Row | None,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
    ) -> CompanionLifestyleStateRecord:
        if row is None:
            return CompanionLifestyleStateRecord(
                client_id=client_id,
                channel=channel,
                thread_id=thread_id,
                timezone_name="Asia/Singapore",
                home_base="Singapore",
                work_area="Tanjong Pagar",
                routine_state="",
                last_state_changed_at="",
                last_morning_checkin_at="",
                last_evening_checkin_at="",
                last_weekend_checkin_at="",
                updated_at="",
            )
        return CompanionLifestyleStateRecord(
            client_id=row["client_id"],
            channel=row["channel"],
            thread_id=row["thread_id"],
            timezone_name=row["timezone_name"],
            home_base=row["home_base"],
            work_area=row["work_area"],
            routine_state=row["routine_state"],
            last_state_changed_at=row["last_state_changed_at"],
            last_morning_checkin_at=row["last_morning_checkin_at"],
            last_evening_checkin_at=row["last_evening_checkin_at"],
            last_weekend_checkin_at=row["last_weekend_checkin_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_companion_daily_schedule(
        self,
        row: sqlite3.Row | None,
        *,
        client_id: str = "",
        schedule_date: str,
        timezone_name: str,
    ) -> CompanionDailyScheduleRecord:
        if row is None:
            return CompanionDailyScheduleRecord(
                client_id=client_id,
                schedule_date=schedule_date,
                timezone_name=timezone_name,
                routine_state_snapshot="",
                morning_plan="",
                lunch_plan="",
                afternoon_plan="",
                dinner_plan="",
                evening_plan="",
                current_plan="",
                next_plan="",
                revision_note="",
                last_explicit_update_at="",
                created_at="",
                updated_at="",
            )
        return CompanionDailyScheduleRecord(
            client_id=row["client_id"],
            schedule_date=row["schedule_date"],
            timezone_name=row["timezone_name"],
            routine_state_snapshot=row["routine_state_snapshot"],
            morning_plan=row["morning_plan"],
            lunch_plan=row["lunch_plan"],
            afternoon_plan=row["afternoon_plan"],
            dinner_plan=row["dinner_plan"],
            evening_plan=row["evening_plan"],
            current_plan=row["current_plan"],
            next_plan=row["next_plan"],
            revision_note=row["revision_note"],
            last_explicit_update_at=row["last_explicit_update_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_companion_self_state(
        self,
        row: sqlite3.Row | None,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
        state_date: str,
        timezone_name: str,
    ) -> CompanionSelfStateRecord:
        if row is None:
            return CompanionSelfStateRecord(
                client_id=client_id,
                channel=channel,
                thread_id=thread_id,
                state_date=state_date,
                timezone_name=timezone_name,
                routine_state_snapshot="",
                internal_state=[],
                opinion_profile=[],
                used_callback_facts=[],
                last_callback_fact="",
                last_callback_at="",
                last_engagement_mode="",
                last_engagement_reason="",
                created_at="",
                updated_at="",
            )
        return CompanionSelfStateRecord(
            client_id=row["client_id"],
            channel=row["channel"],
            thread_id=row["thread_id"],
            state_date=row["state_date"],
            timezone_name=row["timezone_name"],
            routine_state_snapshot=row["routine_state_snapshot"],
            internal_state=json.loads(row["internal_state_json"]),
            opinion_profile=json.loads(row["opinion_profile_json"]),
            used_callback_facts=json.loads(row["used_callback_facts_json"]),
            last_callback_fact=row["last_callback_fact"],
            last_callback_at=row["last_callback_at"],
            last_engagement_mode=row["last_engagement_mode"],
            last_engagement_reason=row["last_engagement_reason"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_companion_reminder(
        self,
        row: sqlite3.Row,
    ) -> CompanionReminderRecord:
        return CompanionReminderRecord(
            reminder_id=int(row["id"]),
            client_id=row["client_id"],
            channel=row["channel"],
            thread_id=row["thread_id"],
            reminder_text=row["reminder_text"],
            due_at=row["due_at"],
            timezone_name=row["timezone_name"],
            status=row["status"],
            created_at=row["created_at"],
            sent_at=row["sent_at"],
            metadata=json.loads(row["metadata_json"]),
        )

    def _get_companion_lifestyle_state_in_connection(
        self,
        connection: sqlite3.Connection,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
    ) -> CompanionLifestyleStateRecord:
        row = connection.execute(
            """
            SELECT * FROM companion_lifestyle_state
            WHERE client_id = ? AND channel = ? AND thread_id = ?
            LIMIT 1
            """,
            (client_id, channel, thread_id),
        ).fetchone()
        return self._row_to_companion_lifestyle_state(
            row,
            client_id=client_id,
            channel=channel,
            thread_id=thread_id,
        )

    def _get_companion_daily_schedule_in_connection(
        self,
        connection: sqlite3.Connection,
        *,
        client_id: str = "",
        schedule_date: str,
        timezone_name: str,
    ) -> CompanionDailyScheduleRecord:
        row = connection.execute(
            """
            SELECT * FROM companion_daily_schedule
            WHERE client_id = ? AND schedule_date = ?
            LIMIT 1
            """,
            (client_id, schedule_date),
        ).fetchone()
        return self._row_to_companion_daily_schedule(
            row,
            client_id=client_id,
            schedule_date=schedule_date,
            timezone_name=timezone_name,
        )

    def _get_companion_self_state_in_connection(
        self,
        connection: sqlite3.Connection,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
        state_date: str,
        timezone_name: str,
    ) -> CompanionSelfStateRecord:
        row = connection.execute(
            """
            SELECT * FROM companion_self_state
            WHERE client_id = ? AND channel = ? AND thread_id = ? AND state_date = ?
            LIMIT 1
            """,
            (client_id, channel, thread_id, state_date),
        ).fetchone()
        return self._row_to_companion_self_state(
            row,
            client_id=client_id,
            channel=channel,
            thread_id=thread_id,
            state_date=state_date,
            timezone_name=timezone_name,
        )

    def _upsert_companion_lifestyle_state_in_connection(
        self,
        connection: sqlite3.Connection,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
        timezone_name: str | None = None,
        home_base: str | None = None,
        work_area: str | None = None,
        routine_state: str | None = None,
        last_state_changed_at: str | None = None,
        last_morning_checkin_at: str | None = None,
        last_evening_checkin_at: str | None = None,
        last_weekend_checkin_at: str | None = None,
    ) -> CompanionLifestyleStateRecord:
        current = self._get_companion_lifestyle_state_in_connection(
            connection,
            client_id=client_id,
            channel=channel,
            thread_id=thread_id,
        )
        now_iso = utc_now().isoformat()
        next_record = CompanionLifestyleStateRecord(
            client_id=client_id,
            channel=channel,
            thread_id=thread_id,
            timezone_name=current.timezone_name if timezone_name is None else timezone_name,
            home_base=current.home_base if home_base is None else home_base,
            work_area=current.work_area if work_area is None else work_area,
            routine_state=current.routine_state if routine_state is None else routine_state,
            last_state_changed_at=current.last_state_changed_at if last_state_changed_at is None else last_state_changed_at,
            last_morning_checkin_at=current.last_morning_checkin_at if last_morning_checkin_at is None else last_morning_checkin_at,
            last_evening_checkin_at=current.last_evening_checkin_at if last_evening_checkin_at is None else last_evening_checkin_at,
            last_weekend_checkin_at=current.last_weekend_checkin_at if last_weekend_checkin_at is None else last_weekend_checkin_at,
            updated_at=now_iso,
        )
        connection.execute(
            """
            INSERT INTO companion_lifestyle_state (
                client_id,
                channel,
                thread_id,
                timezone_name,
                home_base,
                work_area,
                routine_state,
                last_state_changed_at,
                last_morning_checkin_at,
                last_evening_checkin_at,
                last_weekend_checkin_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(client_id, channel, thread_id) DO UPDATE SET
                timezone_name = excluded.timezone_name,
                home_base = excluded.home_base,
                work_area = excluded.work_area,
                routine_state = excluded.routine_state,
                last_state_changed_at = excluded.last_state_changed_at,
                last_morning_checkin_at = excluded.last_morning_checkin_at,
                last_evening_checkin_at = excluded.last_evening_checkin_at,
                last_weekend_checkin_at = excluded.last_weekend_checkin_at,
                updated_at = excluded.updated_at
            """,
            (
                next_record.client_id,
                next_record.channel,
                next_record.thread_id,
                next_record.timezone_name,
                next_record.home_base,
                next_record.work_area,
                next_record.routine_state,
                next_record.last_state_changed_at,
                next_record.last_morning_checkin_at,
                next_record.last_evening_checkin_at,
                next_record.last_weekend_checkin_at,
                next_record.updated_at,
            ),
        )
        return next_record

    def _upsert_companion_daily_schedule_in_connection(
        self,
        connection: sqlite3.Connection,
        *,
        client_id: str = "",
        schedule_date: str,
        timezone_name: str | None = None,
        routine_state_snapshot: str | None = None,
        morning_plan: str | None = None,
        lunch_plan: str | None = None,
        afternoon_plan: str | None = None,
        dinner_plan: str | None = None,
        evening_plan: str | None = None,
        current_plan: str | None = None,
        next_plan: str | None = None,
        revision_note: str | None = None,
        last_explicit_update_at: str | None = None,
    ) -> CompanionDailyScheduleRecord:
        current = self._get_companion_daily_schedule_in_connection(
            connection,
            client_id=client_id,
            schedule_date=schedule_date,
            timezone_name=timezone_name or "Asia/Singapore",
        )
        now_iso = utc_now().isoformat()
        next_record = CompanionDailyScheduleRecord(
            client_id=client_id,
            schedule_date=schedule_date,
            timezone_name=current.timezone_name if timezone_name is None else timezone_name,
            routine_state_snapshot=current.routine_state_snapshot if routine_state_snapshot is None else routine_state_snapshot,
            morning_plan=current.morning_plan if morning_plan is None else morning_plan,
            lunch_plan=current.lunch_plan if lunch_plan is None else lunch_plan,
            afternoon_plan=current.afternoon_plan if afternoon_plan is None else afternoon_plan,
            dinner_plan=current.dinner_plan if dinner_plan is None else dinner_plan,
            evening_plan=current.evening_plan if evening_plan is None else evening_plan,
            current_plan=current.current_plan if current_plan is None else current_plan,
            next_plan=current.next_plan if next_plan is None else next_plan,
            revision_note=current.revision_note if revision_note is None else revision_note,
            last_explicit_update_at=current.last_explicit_update_at if last_explicit_update_at is None else last_explicit_update_at,
            created_at=current.created_at or now_iso,
            updated_at=now_iso,
        )
        connection.execute(
            """
            INSERT INTO companion_daily_schedule (
                client_id,
                schedule_date,
                timezone_name,
                routine_state_snapshot,
                morning_plan,
                lunch_plan,
                afternoon_plan,
                dinner_plan,
                evening_plan,
                current_plan,
                next_plan,
                revision_note,
                last_explicit_update_at,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(client_id, schedule_date) DO UPDATE SET
                timezone_name = excluded.timezone_name,
                routine_state_snapshot = excluded.routine_state_snapshot,
                morning_plan = excluded.morning_plan,
                lunch_plan = excluded.lunch_plan,
                afternoon_plan = excluded.afternoon_plan,
                dinner_plan = excluded.dinner_plan,
                evening_plan = excluded.evening_plan,
                current_plan = excluded.current_plan,
                next_plan = excluded.next_plan,
                revision_note = excluded.revision_note,
                last_explicit_update_at = excluded.last_explicit_update_at,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            (
                next_record.client_id,
                next_record.schedule_date,
                next_record.timezone_name,
                next_record.routine_state_snapshot,
                next_record.morning_plan,
                next_record.lunch_plan,
                next_record.afternoon_plan,
                next_record.dinner_plan,
                next_record.evening_plan,
                next_record.current_plan,
                next_record.next_plan,
                next_record.revision_note,
                next_record.last_explicit_update_at,
                next_record.created_at,
                next_record.updated_at,
            ),
        )
        return next_record

    def _upsert_companion_self_state_in_connection(
        self,
        connection: sqlite3.Connection,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
        state_date: str,
        timezone_name: str | None = None,
        routine_state_snapshot: str | None = None,
        internal_state: list[str] | None = None,
        opinion_profile: list[str] | None = None,
        used_callback_facts: list[str] | None = None,
        last_callback_fact: str | None = None,
        last_callback_at: str | None = None,
        last_engagement_mode: str | None = None,
        last_engagement_reason: str | None = None,
    ) -> CompanionSelfStateRecord:
        current = self._get_companion_self_state_in_connection(
            connection,
            client_id=client_id,
            channel=channel,
            thread_id=thread_id,
            state_date=state_date,
            timezone_name=timezone_name or "Asia/Singapore",
        )
        now_iso = utc_now().isoformat()
        created_at = current.created_at or now_iso
        next_record = CompanionSelfStateRecord(
            client_id=client_id,
            channel=channel,
            thread_id=thread_id,
            state_date=state_date,
            timezone_name=current.timezone_name if timezone_name is None else timezone_name,
            routine_state_snapshot=(
                current.routine_state_snapshot
                if routine_state_snapshot is None else routine_state_snapshot
            ),
            internal_state=current.internal_state if internal_state is None else list(internal_state),
            opinion_profile=current.opinion_profile if opinion_profile is None else list(opinion_profile),
            used_callback_facts=(
                current.used_callback_facts
                if used_callback_facts is None else list(used_callback_facts)
            ),
            last_callback_fact=(
                current.last_callback_fact if last_callback_fact is None else last_callback_fact
            ),
            last_callback_at=(
                current.last_callback_at if last_callback_at is None else last_callback_at
            ),
            last_engagement_mode=(
                current.last_engagement_mode
                if last_engagement_mode is None else last_engagement_mode
            ),
            last_engagement_reason=(
                current.last_engagement_reason
                if last_engagement_reason is None else last_engagement_reason
            ),
            created_at=created_at,
            updated_at=now_iso,
        )
        connection.execute(
            """
            INSERT INTO companion_self_state (
                client_id, channel, thread_id, state_date, timezone_name,
                routine_state_snapshot, internal_state_json, opinion_profile_json,
                used_callback_facts_json, last_callback_fact, last_callback_at,
                last_engagement_mode, last_engagement_reason, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(client_id, channel, thread_id, state_date) DO UPDATE SET
                timezone_name = excluded.timezone_name,
                routine_state_snapshot = excluded.routine_state_snapshot,
                internal_state_json = excluded.internal_state_json,
                opinion_profile_json = excluded.opinion_profile_json,
                used_callback_facts_json = excluded.used_callback_facts_json,
                last_callback_fact = excluded.last_callback_fact,
                last_callback_at = excluded.last_callback_at,
                last_engagement_mode = excluded.last_engagement_mode,
                last_engagement_reason = excluded.last_engagement_reason,
                updated_at = excluded.updated_at
            """,
            (
                next_record.client_id,
                next_record.channel,
                next_record.thread_id,
                next_record.state_date,
                next_record.timezone_name,
                next_record.routine_state_snapshot,
                json.dumps(next_record.internal_state, ensure_ascii=False),
                json.dumps(next_record.opinion_profile, ensure_ascii=False),
                json.dumps(next_record.used_callback_facts, ensure_ascii=False),
                next_record.last_callback_fact,
                next_record.last_callback_at,
                next_record.last_engagement_mode,
                next_record.last_engagement_reason,
                next_record.created_at,
                next_record.updated_at,
            ),
        )
        return next_record

    def _get_client_profile_in_connection(
        self,
        connection: sqlite3.Connection,
        *,
        client_id: str,
    ) -> ClientProfileRecord:
        row = connection.execute(
            """
            SELECT * FROM client_profiles
            WHERE client_id = ?
            LIMIT 1
            """,
            (client_id,),
        ).fetchone()
        return self._row_to_client_profile(row, client_id=client_id)

    def _upsert_client_profile_in_connection(
        self,
        connection: sqlite3.Connection,
        *,
        client_id: str,
        preferred_language: str | None = None,
        watchlist_topics: list[str] | None = None,
        response_style: str | None = None,
        risk_appetite: str | None = None,
        investment_horizon: str | None = None,
        institution_type: str | None = None,
        risk_preference: str | None = None,
        asset_focus: list[str] | None = None,
        market_focus: list[str] | None = None,
        expertise_level: str | None = None,
        activity: str | None = None,
        current_mood: str | None = None,
        emotional_trend: str | None = None,
        stress_level: str | None = None,
        confidence: str | None = None,
        notes: str | None = None,
        personal_facts: list[str] | None = None,
        last_active_at: str | None = None,
        interaction_increment: int = 0,
        timezone_name: str | None = None,
    ) -> ClientProfileRecord:
        current = self._get_client_profile_in_connection(connection, client_id=client_id)
        merged_topics = current.watchlist_topics
        if watchlist_topics:
            merged_topics = sorted(set(current.watchlist_topics).union(watchlist_topics))
        merged_asset_focus = current.asset_focus
        if asset_focus:
            merged_asset_focus = sorted(set(current.asset_focus).union(asset_focus))
        merged_market_focus = current.market_focus
        if market_focus:
            merged_market_focus = sorted(set(current.market_focus).union(market_focus))
        merged_personal_facts = current.personal_facts
        if personal_facts:
            # Dedup by last occurrence so re-mentioned facts refresh recency.
            combined = [*current.personal_facts, *personal_facts]
            seen: set[str] = set()
            deduped: list[str] = []
            for item in reversed(combined):
                if item not in seen:
                    seen.add(item)
                    deduped.append(item)
            deduped.reverse()
            merged_personal_facts = deduped[-20:]
        next_language = preferred_language if preferred_language is not None else current.preferred_language
        next_response_style = response_style if response_style is not None else current.response_style
        next_risk_appetite = risk_appetite if risk_appetite is not None else current.risk_appetite
        next_investment_horizon = (
            investment_horizon if investment_horizon is not None else current.investment_horizon
        )
        next_institution_type = institution_type if institution_type is not None else current.institution_type
        next_risk_preference = risk_preference if risk_preference is not None else current.risk_preference
        next_expertise_level = expertise_level if expertise_level is not None else current.expertise_level
        next_activity = activity if activity is not None else current.activity
        next_current_mood = current_mood if current_mood is not None else current.current_mood
        next_emotional_trend = emotional_trend if emotional_trend is not None else current.emotional_trend
        next_stress_level = stress_level if stress_level is not None else current.stress_level
        next_confidence = confidence if confidence is not None else current.confidence
        next_notes = notes if notes is not None else current.notes
        next_last_active = last_active_at if last_active_at is not None else current.last_active_at
        next_timezone_name = timezone_name if timezone_name is not None else current.timezone_name
        updated_at = utc_now().isoformat()
        total_interactions = current.total_interactions + interaction_increment
        connection.execute(
            """
            INSERT INTO client_profiles (
                client_id,
                preferred_language,
                watchlist_topics_json,
                response_style,
                risk_appetite,
                investment_horizon,
                institution_type,
                risk_preference,
                asset_focus_json,
                market_focus_json,
                expertise_level,
                activity,
                current_mood,
                emotional_trend,
                stress_level,
                confidence,
                notes,
                personal_facts_json,
                last_active_at,
                total_interactions,
                updated_at,
                timezone_name
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(client_id) DO UPDATE SET
                preferred_language = excluded.preferred_language,
                watchlist_topics_json = excluded.watchlist_topics_json,
                response_style = excluded.response_style,
                risk_appetite = excluded.risk_appetite,
                investment_horizon = excluded.investment_horizon,
                institution_type = excluded.institution_type,
                risk_preference = excluded.risk_preference,
                asset_focus_json = excluded.asset_focus_json,
                market_focus_json = excluded.market_focus_json,
                expertise_level = excluded.expertise_level,
                activity = excluded.activity,
                current_mood = excluded.current_mood,
                emotional_trend = excluded.emotional_trend,
                stress_level = excluded.stress_level,
                confidence = excluded.confidence,
                notes = excluded.notes,
                personal_facts_json = excluded.personal_facts_json,
                last_active_at = excluded.last_active_at,
                total_interactions = excluded.total_interactions,
                updated_at = excluded.updated_at,
                timezone_name = excluded.timezone_name
            """,
            (
                client_id,
                next_language,
                json.dumps(merged_topics, ensure_ascii=False, sort_keys=True),
                next_response_style,
                next_risk_appetite,
                next_investment_horizon,
                next_institution_type,
                next_risk_preference,
                json.dumps(merged_asset_focus, ensure_ascii=False, sort_keys=True),
                json.dumps(merged_market_focus, ensure_ascii=False, sort_keys=True),
                next_expertise_level,
                next_activity,
                next_current_mood,
                next_emotional_trend,
                next_stress_level,
                next_confidence,
                next_notes,
                json.dumps(merged_personal_facts, ensure_ascii=False, sort_keys=True),
                next_last_active,
                total_interactions,
                updated_at,
                next_timezone_name,
            ),
        )
        return ClientProfileRecord(
            client_id=client_id,
            preferred_language=next_language,
            watchlist_topics=merged_topics,
            response_style=next_response_style,
            risk_appetite=next_risk_appetite,
            investment_horizon=next_investment_horizon,
            institution_type=next_institution_type,
            risk_preference=next_risk_preference,
            asset_focus=merged_asset_focus,
            market_focus=merged_market_focus,
            expertise_level=next_expertise_level,
            activity=next_activity,
            current_mood=next_current_mood,
            emotional_trend=next_emotional_trend,
            stress_level=next_stress_level,
            confidence=next_confidence,
            notes=next_notes,
            personal_facts=merged_personal_facts,
            last_active_at=next_last_active,
            total_interactions=total_interactions,
            updated_at=updated_at,
            timezone_name=next_timezone_name,
        )

    def _ensure_conversation_thread_in_connection(
        self,
        connection: sqlite3.Connection,
        *,
        client_id: str,
        channel: str,
        thread_id: str,
        timestamp: str | None = None,
    ) -> None:
        active_at = timestamp or utc_now().isoformat()
        connection.execute(
            """
            INSERT INTO conversation_threads (
                client_id,
                channel,
                thread_id,
                opened_at,
                last_active_at,
                status
            ) VALUES (?, ?, ?, ?, ?, 'active')
            ON CONFLICT(client_id, channel, thread_id) DO UPDATE SET
                last_active_at = excluded.last_active_at,
                status = 'active'
            """,
            (client_id, channel, thread_id, active_at, active_at),
        )

    def _search_terms(self, query: str) -> list[str]:
        terms: list[str] = []
        for token in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", query):
            cleaned = token.strip()
            if len(cleaned) < 2:
                continue
            normalized = cleaned.casefold()
            terms.append(normalized)
            if re.fullmatch(r"[\u4e00-\u9fff]+", cleaned) and len(cleaned) > 2:
                terms.extend(cleaned[index : index + 2] for index in range(len(cleaned) - 1))
        if not terms and query.strip():
            fallback = query.casefold().strip()
            if len(fallback) >= 2:
                terms.append(fallback)
        return list(dict.fromkeys(terms))

    def _score_text_match(self, haystack: str, terms: list[str]) -> float:
        if not terms:
            return 0.0
        normalized = haystack.casefold()
        score = 0.0
        for term in terms:
            score += float(normalized.count(term))
        return score
