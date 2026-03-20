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

class SQLiteDocumentMixin:
    def upsert_doc_source(self, record: DocSourceRecord) -> None:
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO doc_source (
                    source_id, source_code, source_name, source_type,
                    country_code, default_language_code, homepage_url,
                    is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.source_id,
                    record.source_code,
                    record.source_name,
                    record.source_type,
                    record.country_code,
                    record.default_language_code,
                    record.homepage_url,
                    int(record.is_active),
                    record.created_at,
                    record.updated_at,
                ),
            )

    def get_doc_source(self, source_id: str) -> DocSourceRecord | None:
        with self._connection(commit=False) as connection:
            row = connection.execute(
                "SELECT * FROM doc_source WHERE source_id = ?",
                (source_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_doc_source(row)

    def list_doc_sources(self, *, active_only: bool = True) -> list[DocSourceRecord]:
        query = "SELECT * FROM doc_source"
        params: list[Any] = []
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY source_id"
        with self._connection(commit=False) as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._row_to_doc_source(row) for row in rows]

    def _row_to_doc_source(self, row: sqlite3.Row) -> DocSourceRecord:
        return DocSourceRecord(
            source_id=row["source_id"],
            source_code=row["source_code"],
            source_name=row["source_name"],
            source_type=row["source_type"],
            country_code=row["country_code"],
            default_language_code=row["default_language_code"] or "",
            homepage_url=row["homepage_url"] or "",
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def upsert_doc_release_family(self, record: DocReleaseFamilyRecord) -> None:
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO doc_release_family (
                    release_family_id, source_id, release_code, release_name,
                    topic_code, country_code, frequency, default_language_code,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.release_family_id,
                    record.source_id,
                    record.release_code,
                    record.release_name,
                    record.topic_code,
                    record.country_code,
                    record.frequency,
                    record.default_language_code,
                    record.created_at,
                    record.updated_at,
                ),
            )

    def get_doc_release_family(self, release_family_id: str) -> DocReleaseFamilyRecord | None:
        with self._connection(commit=False) as connection:
            row = connection.execute(
                "SELECT * FROM doc_release_family WHERE release_family_id = ?",
                (release_family_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_doc_release_family(row)

    def list_doc_release_families(
        self,
        *,
        source_id: str | None = None,
        country_code: str | None = None,
        topic_code: str | None = None,
    ) -> list[DocReleaseFamilyRecord]:
        conditions: list[str] = []
        params: list[Any] = []
        if source_id:
            conditions.append("source_id = ?")
            params.append(source_id)
        if country_code:
            conditions.append("country_code = ?")
            params.append(country_code)
        if topic_code:
            conditions.append("topic_code = ?")
            params.append(topic_code)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                f"SELECT * FROM doc_release_family {where} ORDER BY release_family_id",
                params,
            ).fetchall()
        return [self._row_to_doc_release_family(row) for row in rows]

    def _row_to_doc_release_family(self, row: sqlite3.Row) -> DocReleaseFamilyRecord:
        return DocReleaseFamilyRecord(
            release_family_id=row["release_family_id"],
            source_id=row["source_id"],
            release_code=row["release_code"],
            release_name=row["release_name"],
            topic_code=row["topic_code"],
            country_code=row["country_code"],
            frequency=row["frequency"] or "",
            default_language_code=row["default_language_code"] or "",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def upsert_document(self, record: DocumentRecord) -> None:
        published_precision = record.published_precision or _infer_timestamp_precision(
            record.published_at or record.published_date
        )
        if record.published_at:
            if published_precision == "exact":
                published_at = _safe_utc_iso(record.published_at)
            else:
                published_at = record.published_at[:10]
        elif record.published_date:
            if published_precision == "exact":
                published_at = _safe_utc_iso(record.published_date)
            else:
                published_at = record.published_date
        else:
            published_at = ""
        published_epoch_ms = record.published_epoch_ms or _safe_epoch_ms(published_at or record.published_date)
        created_epoch_ms = record.created_epoch_ms or _safe_epoch_ms(record.created_at)
        updated_epoch_ms = record.updated_epoch_ms or _safe_epoch_ms(record.updated_at)
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO document (
                    document_id, release_family_id, source_id, canonical_url,
                    title, subtitle, document_type, mime_type,
                    language_code, country_code, topic_code,
                    published_date, published_at, published_precision, published_epoch_ms, status, version_no,
                    parent_document_id, hash_sha256,
                    created_at, updated_at, created_epoch_ms, updated_epoch_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.document_id,
                    record.release_family_id or None,
                    record.source_id,
                    record.canonical_url,
                    record.title,
                    record.subtitle,
                    record.document_type,
                    record.mime_type,
                    record.language_code,
                    record.country_code,
                    record.topic_code,
                    record.published_date,
                    published_at or None,
                    published_precision,
                    published_epoch_ms,
                    record.status,
                    record.version_no,
                    record.parent_document_id or None,
                    record.hash_sha256 or None,
                    record.created_at,
                    record.updated_at,
                    created_epoch_ms,
                    updated_epoch_ms,
                ),
            )

    def get_document(self, document_id: str) -> DocumentRecord | None:
        with self._connection(commit=False) as connection:
            row = connection.execute(
                "SELECT * FROM document WHERE document_id = ?",
                (document_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_document(row)

    def get_document_by_url(self, canonical_url: str) -> DocumentRecord | None:
        with self._connection(commit=False) as connection:
            row = connection.execute(
                "SELECT * FROM document WHERE canonical_url = ?",
                (canonical_url,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_document(row)

    def document_exists(self, canonical_url: str) -> bool:
        with self._connection(commit=False) as connection:
            row = connection.execute(
                "SELECT 1 FROM document WHERE canonical_url = ? LIMIT 1",
                (canonical_url,),
            ).fetchone()
        return row is not None

    def list_documents(
        self,
        *,
        source_id: str | None = None,
        release_family_id: str | None = None,
        country_code: str | None = None,
        topic_code: str | None = None,
        status: str | None = None,
        document_type: str | None = None,
        limit: int = 50,
        days: int | None = None,
    ) -> list[DocumentRecord]:
        conditions: list[str] = []
        params: list[Any] = []
        if source_id:
            conditions.append("source_id = ?")
            params.append(source_id)
        if release_family_id:
            conditions.append("release_family_id = ?")
            params.append(release_family_id)
        if country_code:
            conditions.append("country_code = ?")
            params.append(country_code)
        if topic_code:
            conditions.append("topic_code = ?")
            params.append(topic_code)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if document_type:
            conditions.append("document_type = ?")
            params.append(document_type)
        if days is not None:
            cutoff = (date.today() - timedelta(days=days)).isoformat()
            cutoff_dt = datetime.fromisoformat(cutoff).replace(tzinfo=timezone.utc)
            cutoff_epoch_ms = int(cutoff_dt.timestamp() * 1000)
            conditions.append("(published_epoch_ms >= ? OR published_date >= ?)")
            params.extend([cutoff_epoch_ms, cutoff])
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM document
                {where}
                ORDER BY published_epoch_ms DESC, published_date DESC, document_id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_document(row) for row in rows]

    def _row_to_document(self, row: sqlite3.Row) -> DocumentRecord:
        published_precision = row["published_precision"] or _infer_timestamp_precision(
            row["published_at"] or row["published_date"]
        )
        published_at = row["published_at"] or (
            _safe_utc_iso(row["published_date"]) if published_precision == "exact" else row["published_date"]
        )
        return DocumentRecord(
            document_id=row["document_id"],
            release_family_id=row["release_family_id"] or "",
            source_id=row["source_id"],
            canonical_url=row["canonical_url"],
            title=row["title"],
            subtitle=row["subtitle"] or "",
            document_type=row["document_type"],
            mime_type=row["mime_type"],
            language_code=row["language_code"],
            country_code=row["country_code"],
            topic_code=row["topic_code"],
            published_date=row["published_date"],
            published_at=published_at,
            published_precision=published_precision,
            status=row["status"],
            version_no=int(row["version_no"]),
            parent_document_id=row["parent_document_id"] or "",
            hash_sha256=row["hash_sha256"] or "",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            published_epoch_ms=(
                int(row["published_epoch_ms"])
                if row["published_epoch_ms"]
                else _safe_epoch_ms(row["published_at"] or row["published_date"])
            ),
            created_epoch_ms=(
                int(row["created_epoch_ms"])
                if row["created_epoch_ms"]
                else _safe_epoch_ms(row["created_at"])
            ),
            updated_epoch_ms=(
                int(row["updated_epoch_ms"])
                if row["updated_epoch_ms"]
                else _safe_epoch_ms(row["updated_at"])
            ),
        )

    def upsert_document_blob(self, record: DocumentBlobRecord) -> None:
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO document_blob (
                    document_blob_id, document_id, blob_role,
                    storage_path, content_text, content_bytes,
                    byte_size, encoding, parser_name, parser_version,
                    extracted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.document_blob_id,
                    record.document_id,
                    record.blob_role,
                    record.storage_path or None,
                    record.content_text or None,
                    record.content_bytes,
                    record.byte_size,
                    record.encoding or None,
                    record.parser_name or None,
                    record.parser_version or None,
                    record.extracted_at or None,
                ),
            )

    def get_document_blob(
        self,
        document_id: str,
        blob_role: str,
    ) -> DocumentBlobRecord | None:
        with self._connection(commit=False) as connection:
            row = connection.execute(
                "SELECT * FROM document_blob WHERE document_id = ? AND blob_role = ?",
                (document_id, blob_role),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_document_blob(row)

    def list_document_blobs(self, document_id: str) -> list[DocumentBlobRecord]:
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                "SELECT * FROM document_blob WHERE document_id = ? ORDER BY blob_role",
                (document_id,),
            ).fetchall()
        return [self._row_to_document_blob(row) for row in rows]

    def _row_to_document_blob(self, row: sqlite3.Row) -> DocumentBlobRecord:
        return DocumentBlobRecord(
            document_blob_id=row["document_blob_id"],
            document_id=row["document_id"],
            blob_role=row["blob_role"],
            storage_path=row["storage_path"] or "",
            content_text=row["content_text"] or "",
            content_bytes=row["content_bytes"],
            byte_size=int(row["byte_size"]) if row["byte_size"] is not None else 0,
            encoding=row["encoding"] or "",
            parser_name=row["parser_name"] or "",
            parser_version=row["parser_version"] or "",
            extracted_at=row["extracted_at"] or "",
        )

    def upsert_document_extra(self, record: DocumentExtraRecord) -> None:
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO document_extra (
                    document_id, extra_json
                ) VALUES (?, ?)
                """,
                (
                    record.document_id,
                    json.dumps(record.extra_json, ensure_ascii=False, sort_keys=True),
                ),
            )

    def get_document_extra(self, document_id: str) -> DocumentExtraRecord | None:
        with self._connection(commit=False) as connection:
            row = connection.execute(
                "SELECT * FROM document_extra WHERE document_id = ?",
                (document_id,),
            ).fetchone()
        if row is None:
            return None
        return DocumentExtraRecord(
            document_id=row["document_id"],
            extra_json=json.loads(row["extra_json"]),
        )

    def seed_doc_sources_and_families(self, source_configs: dict[str, dict[str, dict[str, Any]]]) -> None:
        """Populate doc_source and doc_release_family from scraper config dicts.

        Args:
            source_configs: Mapping of region label to source_id→config dicts,
                e.g. {"us": {"us_bls_cpi": {...}, ...}, "cn": {...}}.
        """
        now = utc_now().isoformat()
        seen_sources: dict[str, DocSourceRecord] = {}

        for _region, sources in source_configs.items():
            for source_id, cfg in sources.items():
                institution = cfg.get("institution", "")
                country = cfg.get("country", "")
                language = cfg.get("language", "en")

                # Derive source-level key: e.g. "us.bls" from "us_bls_cpi"
                parts = source_id.split("_")
                source_key = f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else source_id

                if source_key not in seen_sources:
                    source_type = self._infer_source_type(institution)
                    homepage = cfg.get("url", "")
                    seen_sources[source_key] = DocSourceRecord(
                        source_id=source_key,
                        source_code=parts[1] if len(parts) >= 2 else source_id,
                        source_name=institution,
                        source_type=source_type,
                        country_code=country,
                        default_language_code=language,
                        homepage_url=homepage,
                        is_active=True,
                        created_at=now,
                        updated_at=now,
                    )
                    self.upsert_doc_source(seen_sources[source_key])

                # Release family
                release_code = "_".join(parts[2:]) if len(parts) > 2 else parts[-1]
                data_category = cfg.get("data_category", "")
                frequency = self._infer_frequency(data_category)

                family = DocReleaseFamilyRecord(
                    release_family_id=source_id.replace("_", "."),
                    source_id=source_key,
                    release_code=release_code,
                    release_name=cfg.get("data_category", release_code).replace("_", " ").title(),
                    topic_code=data_category,
                    country_code=country,
                    frequency=frequency,
                    default_language_code=language,
                    created_at=now,
                    updated_at=now,
                )
                self.upsert_doc_release_family(family)

    def _infer_source_type(institution: str) -> str:
        lower = institution.lower()
        central_banks = [
            "federal reserve", "pboc", "人民银行", "bank of japan", "boj",
            "ecb", "bank of england",
        ]
        if any(cb in lower for cb in central_banks):
            return "central_bank"
        stats = ["统计局", "eurostat", "census", "cabinet office"]
        if any(s in lower for s in stats):
            return "statistics_bureau"
        intl = ["imf", "world bank", "oecd", "s&p global", "caixin"]
        if any(i in lower for i in intl):
            return "intl_org"
        return "government_agency"

    def _infer_frequency(data_category: str) -> str:
        monthly = [
            "inflation", "employment", "consumption", "trade",
            "industrial_production", "monetary", "interest_rate",
            "money_supply", "fx_reserves", "fiscal_policy",
            "bond_issuance", "capital_flows", "housing",
            "consumer_sentiment", "manufacturing",
        ]
        if data_category in monthly:
            return "monthly"
        if data_category in ("gdp", "investment"):
            return "quarterly"
        if data_category in ("monetary_policy", "economic_conditions"):
            return "irregular"
        return "irregular"

