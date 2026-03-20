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

class SQLiteMarketMacroMixin:
    def upsert_calendar_event(self, event: StoredEventRecord) -> None:
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO calendar_events (
                    source,
                    event_id,
                    timestamp,
                    country,
                    indicator,
                    category,
                    importance,
                    actual,
                    forecast,
                    previous,
                    revised_previous,
                    surprise,
                    currency,
                    unit,
                    raw_json,
                    indicator_id,
                    scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.source,
                    event.event_id,
                    event.timestamp,
                    event.country,
                    event.indicator,
                    event.category,
                    event.importance,
                    event.actual,
                    event.forecast,
                    event.previous,
                    event.revised_previous,
                    event.surprise,
                    event.currency,
                    event.unit,
                    json.dumps(event.raw_json, ensure_ascii=True, sort_keys=True),
                    event.indicator_id,
                    utc_now().isoformat(),
                ),
            )

    def insert_market_price(self, price: MarketPriceRecord) -> None:
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                INSERT INTO market_prices (
                    symbol,
                    asset_class,
                    name,
                    price,
                    change_pct,
                    timestamp,
                    scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    price.symbol,
                    price.asset_class,
                    price.name,
                    price.price,
                    price.change_pct,
                    price.timestamp,
                    utc_now().isoformat(),
                ),
            )

    def upsert_central_bank_comm(self, communication: CentralBankCommunicationRecord) -> None:
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO central_bank_comms (
                    source,
                    title,
                    url,
                    timestamp,
                    content_type,
                    speaker,
                    summary,
                    full_text,
                    scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    communication.source,
                    communication.title,
                    communication.url,
                    communication.timestamp,
                    communication.content_type,
                    communication.speaker,
                    communication.summary,
                    communication.full_text,
                    utc_now().isoformat(),
                ),
            )

    def upsert_indicator_observation(self, observation: IndicatorObservationRecord) -> None:
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO indicators (
                    series_id,
                    source,
                    date,
                    value,
                    metadata_json,
                    obs_family_id,
                    scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation.series_id,
                    observation.source,
                    observation.date,
                    observation.value,
                    json.dumps(observation.metadata, ensure_ascii=True, sort_keys=True),
                    observation.obs_family_id,
                    utc_now().isoformat(),
                ),
            )

    def list_recent_events(
        self,
        *,
        limit: int = 10,
        days: int = 7,
        released_only: bool = False,
        importance: str | None = None,
        country: str | None = None,
        category: str | None = None,
    ) -> list[StoredEventRecord]:
        cutoff = int((utc_now() - timedelta(days=days)).timestamp())
        conditions = ["timestamp >= ?"]
        params: list[Any] = [cutoff]
        if released_only:
            conditions.append("actual IS NOT NULL")
        if importance:
            conditions.append("importance = ?")
            params.append(importance)
        if country:
            conditions.append("country = ?")
            params.append(country)
        if category:
            conditions.append("category = ?")
            params.append(category)
        params.append(limit)
        # Only fixed SQL fragments are appended here; user input stays parameterized.
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM calendar_events
                WHERE {' AND '.join(conditions)}
                ORDER BY timestamp DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def list_upcoming_events(
        self,
        *,
        limit: int = 10,
        importance: str | None = None,
        country: str | None = None,
        category: str | None = None,
    ) -> list[StoredEventRecord]:
        now_epoch = int(utc_now().timestamp())
        conditions = ["timestamp >= ?"]
        params: list[Any] = [now_epoch]
        if importance:
            conditions.append("importance = ?")
            params.append(importance)
        if country:
            conditions.append("country = ?")
            params.append(country)
        if category:
            conditions.append("category = ?")
            params.append(category)
        params.append(limit)
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM calendar_events
                WHERE {' AND '.join(conditions)}
                ORDER BY timestamp ASC, id ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def list_events_in_range(
        self,
        *,
        date_from: int,
        date_to: int,
        limit: int = 50,
        importance: str | None = None,
        country: str | None = None,
        category: str | None = None,
        released_only: bool = False,
    ) -> list[StoredEventRecord]:
        conditions = ["timestamp >= ?", "timestamp <= ?"]
        params: list[Any] = [date_from, date_to]
        if released_only:
            conditions.append("actual IS NOT NULL")
        if importance:
            conditions.append("importance = ?")
            params.append(importance)
        if country:
            conditions.append("country = ?")
            params.append(country)
        if category:
            conditions.append("category = ?")
            params.append(category)
        params.append(limit)
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM calendar_events
                WHERE {' AND '.join(conditions)}
                ORDER BY timestamp ASC, id ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def list_today_events(
        self,
        *,
        limit: int = 50,
        importance: str | None = None,
        country: str | None = None,
        category: str | None = None,
    ) -> list[StoredEventRecord]:
        today = datetime.now(timezone.utc).date()
        date_from = int(datetime(today.year, today.month, today.day, tzinfo=timezone.utc).timestamp())
        date_to = int(datetime(today.year, today.month, today.day, 23, 59, 59, tzinfo=timezone.utc).timestamp())
        return self.list_events_in_range(
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            importance=importance,
            country=country,
            category=category,
        )

    def list_indicator_releases(
        self,
        *,
        indicator_keyword: str,
        limit: int = 12,
    ) -> list[StoredEventRecord]:
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT * FROM calendar_events
                WHERE LOWER(indicator) LIKE ? AND actual IS NOT NULL
                ORDER BY timestamp DESC, id DESC
                LIMIT ?
                """,
                (f"%{indicator_keyword.lower()}%", limit),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def latest_market_prices(self) -> list[MarketPriceRecord]:
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT latest.* FROM market_prices latest
                INNER JOIN (
                    SELECT symbol, MAX(id) AS max_id
                    FROM market_prices
                    GROUP BY symbol
                ) grouped ON latest.id = grouped.max_id
                ORDER BY latest.asset_class ASC, latest.symbol ASC
                """
            ).fetchall()
        return [self._row_to_market_price(row) for row in rows]

    def list_recent_central_bank_comms(
        self,
        *,
        source: str = "fed",
        limit: int = 5,
        days: int = 14,
        speaker: str | None = None,
        content_type: str | None = None,
    ) -> list[CentralBankCommunicationRecord]:
        cutoff = int((utc_now() - timedelta(days=days)).timestamp())
        conditions = ["source = ?", "timestamp >= ?"]
        params: list[Any] = [source, cutoff]
        if speaker:
            conditions.append("LOWER(speaker) LIKE ?")
            params.append(f"%{speaker.lower()}%")
        if content_type:
            conditions.append("content_type = ?")
            params.append(content_type)
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM central_bank_comms
                WHERE {' AND '.join(conditions)}
                ORDER BY timestamp DESC, id DESC
                LIMIT ?
                """,
                [*params, limit],
            ).fetchall()
        return [self._row_to_comm(row) for row in rows]

    def get_indicator_history(self, series_id: str, *, limit: int = 12) -> list[IndicatorObservationRecord]:
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT * FROM indicators
                WHERE series_id = ?
                ORDER BY date DESC, id DESC
                LIMIT ?
                """,
                (series_id, limit),
            ).fetchall()
        return [self._row_to_indicator(row) for row in rows]

    def latest_released_event(self, *, indicator_keyword: str | None = None) -> StoredEventRecord | None:
        params: list[Any] = []
        conditions = ["actual IS NOT NULL"]
        if indicator_keyword:
            conditions.append("LOWER(indicator) LIKE ?")
            params.append(f"%{indicator_keyword.lower()}%")
        # Only fixed SQL fragments are appended here; user input stays parameterized.
        with self._connection(commit=False) as connection:
            row = connection.execute(
                f"""
                SELECT * FROM calendar_events
                WHERE {' AND '.join(conditions)}
                ORDER BY importance DESC, timestamp DESC, id DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        return self._row_to_event(row) if row is not None else None

    def _row_to_event(self, row: sqlite3.Row) -> StoredEventRecord:
        return StoredEventRecord(
            source=row["source"],
            event_id=row["event_id"],
            timestamp=int(row["timestamp"]),
            country=row["country"],
            indicator=row["indicator"],
            category=row["category"],
            importance=row["importance"],
            actual=row["actual"],
            forecast=row["forecast"],
            previous=row["previous"],
            revised_previous=row["revised_previous"],
            surprise=row["surprise"],
            currency=row["currency"],
            unit=row["unit"],
            raw_json=json.loads(row["raw_json"]),
            indicator_id=row["indicator_id"],
        )

    def _row_to_market_price(self, row: sqlite3.Row) -> MarketPriceRecord:
        return MarketPriceRecord(
            symbol=row["symbol"],
            asset_class=row["asset_class"],
            name=row["name"],
            price=float(row["price"]),
            change_pct=float(row["change_pct"]) if row["change_pct"] is not None else None,
            timestamp=int(row["timestamp"]),
        )

    def _row_to_comm(self, row: sqlite3.Row) -> CentralBankCommunicationRecord:
        return CentralBankCommunicationRecord(
            source=row["source"],
            title=row["title"],
            url=row["url"],
            timestamp=int(row["timestamp"]),
            content_type=row["content_type"],
            speaker=row["speaker"],
            summary=row["summary"],
            full_text=row["full_text"],
        )

    def _row_to_indicator(self, row: sqlite3.Row) -> IndicatorObservationRecord:
        return IndicatorObservationRecord(
            series_id=row["series_id"],
            source=row["source"],
            date=row["date"],
            value=float(row["value"]),
            metadata=json.loads(row["metadata_json"]),
        )

    def upsert_indicator_vintage(self, vintage: IndicatorVintageRecord) -> None:
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO indicator_vintages (
                    series_id,
                    source,
                    observation_date,
                    vintage_date,
                    value,
                    metadata_json,
                    obs_family_id,
                    scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    vintage.series_id,
                    vintage.source,
                    vintage.observation_date,
                    vintage.vintage_date,
                    vintage.value,
                    json.dumps(vintage.metadata, ensure_ascii=True, sort_keys=True),
                    vintage.obs_family_id,
                    utc_now().isoformat(),
                ),
            )

    def get_vintage_history(
        self, series_id: str, observation_date: str,
    ) -> list[IndicatorVintageRecord]:
        """Return all vintages for a given series_id + observation_date."""
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT * FROM indicator_vintages
                WHERE series_id = ? AND observation_date = ?
                ORDER BY vintage_date ASC
                """,
                (series_id, observation_date),
            ).fetchall()
        return [self._row_to_vintage(row) for row in rows]

    def get_vintages_for_series(
        self, series_id: str, *, limit: int = 50,
    ) -> list[IndicatorVintageRecord]:
        """Return the most recent vintage records for a series."""
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT * FROM indicator_vintages
                WHERE series_id = ?
                ORDER BY vintage_date DESC, observation_date DESC
                LIMIT ?
                """,
                (series_id, limit),
            ).fetchall()
        return [self._row_to_vintage(row) for row in rows]

    def _row_to_vintage(self, row: sqlite3.Row) -> IndicatorVintageRecord:
        return IndicatorVintageRecord(
            series_id=row["series_id"],
            source=row["source"],
            observation_date=row["observation_date"],
            vintage_date=row["vintage_date"],
            value=float(row["value"]),
            metadata=json.loads(row["metadata_json"]),
        )

