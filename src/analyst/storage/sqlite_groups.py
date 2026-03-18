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
    CompanionLifestyleStateRecord,
    CompanionDailyScheduleRecord,
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

class SQLiteGroupMixin:
    def upsert_group_profile(
        self,
        *,
        group_id: str,
        group_name: str = "",
        group_topic: str = "",
        group_notes: str = "",
        member_count: int = 0,
    ) -> None:
        now = utc_now().isoformat()
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                INSERT INTO group_profiles (group_id, group_name, group_topic, group_notes, member_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(group_id) DO UPDATE SET
                    group_name = CASE WHEN excluded.group_name != '' THEN excluded.group_name ELSE group_profiles.group_name END,
                    group_topic = CASE WHEN excluded.group_topic != '' THEN excluded.group_topic ELSE group_profiles.group_topic END,
                    group_notes = CASE WHEN excluded.group_notes != '' THEN excluded.group_notes ELSE group_profiles.group_notes END,
                    member_count = CASE WHEN excluded.member_count > 0 THEN excluded.member_count ELSE group_profiles.member_count END,
                    updated_at = excluded.updated_at
                """,
                (group_id, group_name, group_topic, group_notes, member_count, now, now),
            )

    def get_group_profile(self, group_id: str) -> GroupProfileRecord:
        with self._connection(commit=False) as connection:
            row = connection.execute(
                "SELECT * FROM group_profiles WHERE group_id = ? LIMIT 1",
                (group_id,),
            ).fetchone()
        if row is None:
            now = utc_now().isoformat()
            return GroupProfileRecord(
                group_id=group_id,
                group_name="",
                group_topic="",
                group_notes="",
                bot_relational_role="",
                member_count=0,
                created_at=now,
                updated_at=now,
            )
        return GroupProfileRecord(
            group_id=row["group_id"],
            group_name=row["group_name"],
            group_topic=row["group_topic"],
            group_notes=row["group_notes"],
            bot_relational_role=row["bot_relational_role"],
            member_count=row["member_count"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def upsert_group_member(
        self,
        *,
        group_id: str,
        user_id: str,
        display_name: str = "",
        role_in_group: str = "",
        personality_notes: str = "",
    ) -> None:
        now = utc_now().isoformat()
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                INSERT INTO group_members (group_id, user_id, display_name, role_in_group, personality_notes, first_seen_at, last_seen_at, message_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(group_id, user_id) DO UPDATE SET
                    display_name = CASE WHEN excluded.display_name != '' THEN excluded.display_name ELSE group_members.display_name END,
                    role_in_group = CASE WHEN excluded.role_in_group != '' THEN excluded.role_in_group ELSE group_members.role_in_group END,
                    personality_notes = CASE WHEN excluded.personality_notes != '' THEN excluded.personality_notes ELSE group_members.personality_notes END,
                    last_seen_at = excluded.last_seen_at,
                    message_count = group_members.message_count + 1
                """,
                (group_id, user_id, display_name, role_in_group, personality_notes, now, now),
            )

    def list_group_members(self, group_id: str, *, limit: int = 20) -> list[GroupMemberRecord]:
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                "SELECT * FROM group_members WHERE group_id = ? ORDER BY last_seen_at DESC LIMIT ?",
                (group_id, limit),
            ).fetchall()
        return [
            GroupMemberRecord(
                group_id=row["group_id"],
                user_id=row["user_id"],
                display_name=row["display_name"],
                role_in_group=row["role_in_group"],
                personality_notes=row["personality_notes"],
                relational_role=row["relational_role"],
                first_seen_at=row["first_seen_at"],
                last_seen_at=row["last_seen_at"],
                message_count=row["message_count"],
            )
            for row in rows
        ]

    def update_group_member_inference(
        self,
        *,
        group_id: str,
        user_id: str,
        role_in_group: str = "",
        personality_notes: str = "",
    ) -> None:
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                UPDATE group_members
                SET role_in_group = ?, personality_notes = ?
                WHERE group_id = ? AND user_id = ?
                """,
                (role_in_group, personality_notes, group_id, user_id),
            )

    def update_group_member_relational_role(
        self,
        *,
        group_id: str,
        user_id: str,
        relational_role: str,
    ) -> None:
        with self._connection(commit=True) as connection:
            connection.execute(
                "UPDATE group_members SET relational_role = ? WHERE group_id = ? AND user_id = ?",
                (relational_role, group_id, user_id),
            )

    def update_group_bot_relational_role(
        self,
        *,
        group_id: str,
        bot_relational_role: str,
    ) -> None:
        now = utc_now().isoformat()
        with self._connection(commit=True) as connection:
            # Ensure group_profiles row exists before updating
            connection.execute(
                """
                INSERT INTO group_profiles (group_id, group_name, group_topic, group_notes, member_count, created_at, updated_at)
                VALUES (?, '', '', '', 0, ?, ?)
                ON CONFLICT(group_id) DO NOTHING
                """,
                (group_id, now, now),
            )
            connection.execute(
                "UPDATE group_profiles SET bot_relational_role = ? WHERE group_id = ?",
                (bot_relational_role, group_id),
            )

    def append_group_message(
        self,
        *,
        group_id: str,
        thread_id: str = "main",
        user_id: str,
        display_name: str,
        content: str,
    ) -> int:
        now = utc_now().isoformat()
        with self._connection(commit=True) as connection:
            cursor = connection.execute(
                """
                INSERT INTO group_messages (group_id, thread_id, user_id, display_name, content, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (group_id, thread_id, user_id, display_name, content, now),
            )
            return cursor.lastrowid or 0

    def list_group_messages(
        self,
        group_id: str,
        thread_id: str = "main",
        *,
        limit: int = 30,
    ) -> list[GroupMessageRecord]:
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT id, group_id, thread_id, user_id, display_name, content, created_at
                FROM group_messages
                WHERE group_id = ? AND thread_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (group_id, thread_id, limit),
            ).fetchall()
        records = [
            GroupMessageRecord(
                message_id=row["id"],
                group_id=row["group_id"],
                thread_id=row["thread_id"],
                user_id=row["user_id"],
                display_name=row["display_name"],
                content=row["content"],
                created_at=row["created_at"],
            )
            for row in rows
        ]
        records.reverse()  # chronological order
        return records

    def list_recent_group_messages(
        self,
        group_id: str,
        *,
        limit: int = 30,
    ) -> list[GroupMessageRecord]:
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT id, group_id, thread_id, user_id, display_name, content, created_at
                FROM group_messages
                WHERE group_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (group_id, limit),
            ).fetchall()
        records = [
            GroupMessageRecord(
                message_id=row["id"],
                group_id=row["group_id"],
                thread_id=row["thread_id"],
                user_id=row["user_id"],
                display_name=row["display_name"],
                content=row["content"],
                created_at=row["created_at"],
            )
            for row in rows
        ]
        records.reverse()  # chronological order
        return records

    def list_group_messages_since(
        self,
        group_id: str,
        thread_id: str,
        since_message_id: int,
        *,
        limit: int = 50,
    ) -> list[GroupMessageRecord]:
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT id, group_id, thread_id, user_id, display_name, content, created_at
                FROM group_messages
                WHERE group_id = ? AND thread_id = ? AND id > ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (group_id, thread_id, since_message_id, limit),
            ).fetchall()
        return [
            GroupMessageRecord(
                message_id=row["id"],
                group_id=row["group_id"],
                thread_id=row["thread_id"],
                user_id=row["user_id"],
                display_name=row["display_name"],
                content=row["content"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def get_autonomous_message_count_today(
        self,
        group_id: str,
        today_date: str,
    ) -> int:
        with self._connection(commit=False) as connection:
            row = connection.execute(
                "SELECT autonomous_messages_today, autonomous_messages_date "
                "FROM group_profiles WHERE group_id = ? LIMIT 1",
                (group_id,),
            ).fetchone()
        if row is None:
            return 0
        if row["autonomous_messages_date"] != today_date:
            return 0
        return int(row["autonomous_messages_today"])

    def increment_autonomous_message_count(
        self,
        group_id: str,
        today_date: str,
        now_iso: str,
    ) -> int:
        with self._connection(commit=True) as connection:
            row = connection.execute(
                "SELECT autonomous_messages_today, autonomous_messages_date "
                "FROM group_profiles WHERE group_id = ? LIMIT 1",
                (group_id,),
            ).fetchone()
            if row is None:
                # Create a minimal profile row first
                connection.execute(
                    "INSERT OR IGNORE INTO group_profiles "
                    "(group_id, group_name, group_topic, group_notes, member_count, "
                    "created_at, updated_at, autonomous_messages_today, "
                    "autonomous_messages_date, last_autonomous_at) "
                    "VALUES (?, '', '', '', 0, ?, ?, 1, ?, ?)",
                    (group_id, now_iso, now_iso, today_date, now_iso),
                )
                return 1
            if row["autonomous_messages_date"] != today_date:
                new_count = 1
            else:
                new_count = int(row["autonomous_messages_today"]) + 1
            connection.execute(
                "UPDATE group_profiles SET "
                "autonomous_messages_today = ?, autonomous_messages_date = ?, "
                "last_autonomous_at = ?, updated_at = ? "
                "WHERE group_id = ?",
                (new_count, today_date, now_iso, now_iso, group_id),
            )
            return new_count

