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

class SQLiteObservationFamilyMixin:
    def upsert_obs_source(self, record: ObsSourceRecord) -> None:
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO obs_source (
                    source_id, source_code, source_name, source_type,
                    country_code, homepage_url, api_base_url,
                    is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.source_id,
                    record.source_code,
                    record.source_name,
                    record.source_type,
                    record.country_code,
                    record.homepage_url,
                    record.api_base_url,
                    int(record.is_active),
                    record.created_at,
                    record.updated_at,
                ),
            )

    def get_obs_source(self, source_id: str) -> ObsSourceRecord | None:
        with self._connection(commit=False) as connection:
            row = connection.execute(
                "SELECT * FROM obs_source WHERE source_id = ?",
                (source_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_obs_source(row)

    def list_obs_sources(self, *, active_only: bool = True) -> list[ObsSourceRecord]:
        query = "SELECT * FROM obs_source"
        params: list[Any] = []
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY source_id"
        with self._connection(commit=False) as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._row_to_obs_source(row) for row in rows]

    def _row_to_obs_source(self, row: sqlite3.Row) -> ObsSourceRecord:
        return ObsSourceRecord(
            source_id=row["source_id"],
            source_code=row["source_code"],
            source_name=row["source_name"],
            source_type=row["source_type"],
            country_code=row["country_code"],
            homepage_url=row["homepage_url"] or "",
            api_base_url=row["api_base_url"] or "",
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def upsert_obs_family(self, record: ObsFamilyRecord) -> None:
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO obs_family (
                    family_id, source_id, provider_series_id, canonical_name,
                    short_name, unit, frequency, seasonal_adjustment,
                    country_code, topic_code, category,
                    is_active, has_vintages, metadata_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.family_id,
                    record.source_id,
                    record.provider_series_id,
                    record.canonical_name,
                    record.short_name,
                    record.unit,
                    record.frequency,
                    record.seasonal_adjustment,
                    record.country_code,
                    record.topic_code,
                    record.category,
                    int(record.is_active),
                    int(record.has_vintages),
                    json.dumps(record.metadata, ensure_ascii=False, sort_keys=True),
                    record.created_at,
                    record.updated_at,
                ),
            )

    def get_obs_family(self, family_id: str) -> ObsFamilyRecord | None:
        with self._connection(commit=False) as connection:
            row = connection.execute(
                "SELECT * FROM obs_family WHERE family_id = ?",
                (family_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_obs_family(row)

    def get_obs_family_by_series(
        self, source_id: str, provider_series_id: str,
    ) -> ObsFamilyRecord | None:
        with self._connection(commit=False) as connection:
            row = connection.execute(
                "SELECT * FROM obs_family WHERE source_id = ? AND provider_series_id = ?",
                (source_id, provider_series_id),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_obs_family(row)

    def list_obs_families(
        self,
        *,
        source_id: str | None = None,
        country_code: str | None = None,
        topic_code: str | None = None,
        frequency: str | None = None,
        active_only: bool = True,
    ) -> list[ObsFamilyRecord]:
        conditions: list[str] = []
        params: list[Any] = []
        if active_only:
            conditions.append("is_active = 1")
        if source_id:
            conditions.append("source_id = ?")
            params.append(source_id)
        if country_code:
            conditions.append("country_code = ?")
            params.append(country_code)
        if topic_code:
            conditions.append("topic_code = ?")
            params.append(topic_code)
        if frequency:
            conditions.append("frequency = ?")
            params.append(frequency)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                f"SELECT * FROM obs_family {where} ORDER BY family_id",
                params,
            ).fetchall()
        return [self._row_to_obs_family(row) for row in rows]

    def _row_to_obs_family(self, row: sqlite3.Row) -> ObsFamilyRecord:
        return ObsFamilyRecord(
            family_id=row["family_id"],
            source_id=row["source_id"],
            provider_series_id=row["provider_series_id"],
            canonical_name=row["canonical_name"],
            short_name=row["short_name"] or "",
            unit=row["unit"] or "",
            frequency=row["frequency"] or "irregular",
            seasonal_adjustment=row["seasonal_adjustment"] or "none",
            country_code=row["country_code"],
            topic_code=row["topic_code"] or "",
            category=row["category"] or "",
            is_active=bool(row["is_active"]),
            has_vintages=bool(row["has_vintages"]),
            metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else {},
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def upsert_obs_family_document(self, record: ObsFamilyDocumentRecord) -> None:
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO obs_family_document (
                    family_id, release_family_id, relationship, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    record.family_id,
                    record.release_family_id,
                    record.relationship,
                    record.created_at,
                ),
            )

    def list_obs_families_for_release(
        self, release_family_id: str,
    ) -> list[ObsFamilyRecord]:
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT f.* FROM obs_family f
                JOIN obs_family_document d ON f.family_id = d.family_id
                WHERE d.release_family_id = ?
                ORDER BY f.family_id
                """,
                (release_family_id,),
            ).fetchall()
        return [self._row_to_obs_family(row) for row in rows]

    def list_releases_for_obs_family(
        self, family_id: str,
    ) -> list[DocReleaseFamilyRecord]:
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT r.* FROM doc_release_family r
                JOIN obs_family_document d ON r.release_family_id = d.release_family_id
                WHERE d.family_id = ?
                ORDER BY r.release_family_id
                """,
                (family_id,),
            ).fetchall()
        return [self._row_to_doc_release_family(row) for row in rows]

    def seed_obs_sources_and_families(self) -> None:
        """Populate obs_source, obs_family, and obs_family_document tables
        from the module-level seed data constants."""
        now = utc_now().isoformat()

        # 1. Seed obs_source entries
        for src_id, code, name, stype, country, homepage, api_url in _OBS_SOURCE_DEFS:
            self.upsert_obs_source(ObsSourceRecord(
                source_id=src_id,
                source_code=code,
                source_name=name,
                source_type=stype,
                country_code=country,
                homepage_url=homepage,
                api_base_url=api_url,
                is_active=True,
                created_at=now,
                updated_at=now,
            ))

        # 2. Seed obs_family entries from all maps
        source_maps: list[tuple[str, dict[str, tuple[str, str, str, str, str]]]] = [
            ("fred", _FRED_FAMILY_MAP),
            ("eia", _EIA_FAMILY_MAP),
            ("treasury_fiscal", _TREASURY_FAMILY_MAP),
            ("nyfed", _NYFED_FAMILY_MAP),
            ("imf", _IMF_FAMILY_MAP),
            ("eurostat", _EUROSTAT_FAMILY_MAP),
            ("bis", _BIS_FAMILY_MAP),
            ("ecb", _ECB_FAMILY_MAP),
            ("oecd", _OECD_FAMILY_MAP),
            ("worldbank", _WORLDBANK_FAMILY_MAP),
        ]
        for source_id, family_map in source_maps:
            for series_id, (fam_id, canon_name, unit, freq, sa) in family_map.items():
                parts = fam_id.split(".")
                topic = parts[1] if len(parts) > 1 else ""
                category = parts[2] if len(parts) > 2 else ""
                self.upsert_obs_family(ObsFamilyRecord(
                    family_id=fam_id,
                    source_id=source_id,
                    provider_series_id=series_id,
                    canonical_name=canon_name,
                    short_name="",
                    unit=unit,
                    frequency=freq,
                    seasonal_adjustment=sa,
                    country_code=parts[0].upper() if parts else "US",
                    topic_code=topic,
                    category=category,
                    is_active=True,
                    has_vintages=series_id in _VINTAGE_FAMILY_IDS,
                    created_at=now,
                    updated_at=now,
                ))

        # 3. Seed obs_family_document links (only if both sides exist)
        for fam_id, rel_fam_id, relationship in _OBS_DOC_LINKS:
            if self.get_obs_family(fam_id) and self.get_doc_release_family(rel_fam_id):
                self.upsert_obs_family_document(ObsFamilyDocumentRecord(
                    family_id=fam_id,
                    release_family_id=rel_fam_id,
                    relationship=relationship,
                    created_at=now,
                ))

    def backfill_obs_family_ids(self) -> int:
        """Set obs_family_id on existing indicators/vintages rows from obs_family table.
        Returns total number of rows updated."""
        with self._connection(commit=True) as connection:
            cur1 = connection.execute(
                """
                UPDATE indicators SET obs_family_id = (
                    SELECT family_id FROM obs_family
                    WHERE obs_family.provider_series_id = indicators.series_id
                      AND obs_family.source_id = indicators.source
                ) WHERE obs_family_id IS NULL
                """
            )
            cur2 = connection.execute(
                """
                UPDATE indicator_vintages SET obs_family_id = (
                    SELECT family_id FROM obs_family
                    WHERE obs_family.provider_series_id = indicator_vintages.series_id
                      AND obs_family.source_id = indicator_vintages.source
                ) WHERE obs_family_id IS NULL
                """
            )
        return (cur1.rowcount or 0) + (cur2.rowcount or 0)

    def build_obs_family_lookup(self) -> dict[tuple[str, str], str]:
        """Build a lookup dict mapping (source_id, provider_series_id) -> family_id."""
        families = self.list_obs_families(active_only=False)
        return {(f.source_id, f.provider_series_id): f.family_id for f in families}

