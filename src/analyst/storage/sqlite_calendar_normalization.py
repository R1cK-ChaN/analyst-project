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

class SQLiteCalendarNormalizationMixin:
    def upsert_calendar_indicator(self, record: CalendarIndicatorRecord) -> None:
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO calendar_indicator (
                    indicator_id, canonical_name, topic, country_code,
                    frequency, unit, obs_family_id, is_active,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.indicator_id,
                    record.canonical_name,
                    record.topic,
                    record.country_code,
                    record.frequency,
                    record.unit,
                    record.obs_family_id,
                    int(record.is_active),
                    record.created_at,
                    record.updated_at,
                ),
            )

    def get_calendar_indicator(self, indicator_id: str) -> CalendarIndicatorRecord | None:
        with self._connection(commit=False) as connection:
            row = connection.execute(
                "SELECT * FROM calendar_indicator WHERE indicator_id = ?",
                (indicator_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_calendar_indicator(row)

    def list_calendar_indicators(
        self,
        *,
        country_code: str | None = None,
        topic: str | None = None,
        active_only: bool = True,
    ) -> list[CalendarIndicatorRecord]:
        conditions: list[str] = []
        params: list[Any] = []
        if active_only:
            conditions.append("is_active = 1")
        if country_code:
            conditions.append("country_code = ?")
            params.append(country_code)
        if topic:
            conditions.append("topic = ?")
            params.append(topic)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                f"SELECT * FROM calendar_indicator {where} ORDER BY indicator_id",
                params,
            ).fetchall()
        return [self._row_to_calendar_indicator(row) for row in rows]

    def upsert_calendar_indicator_alias(self, record: CalendarIndicatorAliasRecord) -> None:
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO calendar_indicator_alias (
                    alias_normalized, indicator_id, source, country_code,
                    alias_original, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.alias_normalized,
                    record.indicator_id,
                    record.source,
                    record.country_code,
                    record.alias_original,
                    record.created_at,
                ),
            )

    def resolve_calendar_alias(
        self, alias_text: str, source: str, country: str,
    ) -> str | None:
        from analyst.ingestion.scrapers._common import normalize_indicator_name
        normalized = normalize_indicator_name(alias_text)
        with self._connection(commit=False) as connection:
            row = connection.execute(
                """
                SELECT indicator_id FROM calendar_indicator_alias
                WHERE alias_normalized = ? AND source = ? AND country_code = ?
                """,
                (normalized, source, country),
            ).fetchone()
        return row["indicator_id"] if row else None

    def list_aliases_for_indicator(self, indicator_id: str) -> list[CalendarIndicatorAliasRecord]:
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                "SELECT * FROM calendar_indicator_alias WHERE indicator_id = ? ORDER BY source, alias_normalized",
                (indicator_id,),
            ).fetchall()
        return [
            CalendarIndicatorAliasRecord(
                alias_normalized=row["alias_normalized"],
                indicator_id=row["indicator_id"],
                source=row["source"],
                country_code=row["country_code"],
                alias_original=row["alias_original"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def seed_calendar_indicators(self) -> None:
        """Populate calendar_indicator and calendar_indicator_alias tables
        from the module-level seed data constants."""
        from analyst.ingestion.scrapers._common import normalize_indicator_name
        now = utc_now().isoformat()

        for ind_id, canon, topic, cc, freq, unit, obs_fam in _CALENDAR_INDICATOR_DEFS:
            self.upsert_calendar_indicator(CalendarIndicatorRecord(
                indicator_id=ind_id,
                canonical_name=canon,
                topic=topic,
                country_code=cc,
                frequency=freq,
                unit=unit,
                obs_family_id=obs_fam or None,
                is_active=True,
                created_at=now,
                updated_at=now,
            ))

        for alias_orig, ind_id, source, cc in _CALENDAR_ALIAS_DEFS:
            self.upsert_calendar_indicator_alias(CalendarIndicatorAliasRecord(
                alias_normalized=normalize_indicator_name(alias_orig),
                indicator_id=ind_id,
                source=source,
                country_code=cc,
                alias_original=alias_orig,
                created_at=now,
            ))

    def backfill_calendar_indicator_ids(self) -> int:
        """Set indicator_id on existing calendar_events rows from the alias table.
        Returns the number of rows updated."""
        from analyst.ingestion.scrapers._common import normalize_indicator_name  # noqa: F811
        with self._connection(commit=True) as connection:
            cur = connection.execute(
                """
                UPDATE calendar_events SET indicator_id = (
                    SELECT a.indicator_id FROM calendar_indicator_alias a
                    WHERE a.alias_normalized = LOWER(TRIM(calendar_events.indicator))
                      AND a.source = calendar_events.source
                      AND a.country_code = calendar_events.country
                ) WHERE indicator_id IS NULL
                """
            )
        return cur.rowcount or 0

    def list_indicator_releases_by_id(
        self, indicator_id: str, *, limit: int = 12,
    ) -> list[StoredEventRecord]:
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT * FROM calendar_events
                WHERE indicator_id = ? AND actual IS NOT NULL
                ORDER BY timestamp DESC, id DESC
                LIMIT ?
                """,
                (indicator_id, limit),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def _row_to_calendar_indicator(self, row: sqlite3.Row) -> CalendarIndicatorRecord:
        return CalendarIndicatorRecord(
            indicator_id=row["indicator_id"],
            canonical_name=row["canonical_name"],
            topic=row["topic"],
            country_code=row["country_code"],
            frequency=row["frequency"],
            unit=row["unit"],
            obs_family_id=row["obs_family_id"],
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

