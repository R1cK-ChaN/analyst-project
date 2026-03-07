from __future__ import annotations

from contextlib import contextmanager
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Iterator

from analyst.contracts import utc_now


def default_engine_db_path(root: Path | None = None) -> Path:
    base = root or Path.cwd()
    return base / ".analyst" / "engine.db"


@dataclass(frozen=True)
class StoredEventRecord:
    source: str
    event_id: str
    datetime_utc: str
    country: str
    indicator: str
    category: str
    importance: str
    actual: str | None = None
    forecast: str | None = None
    previous: str | None = None
    revised_previous: str | None = None
    surprise: float | None = None
    unit: str = ""
    raw_json: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MarketPriceRecord:
    symbol: str
    asset_class: str
    price: float
    change_pct: float | None
    datetime_utc: str
    name: str = ""


@dataclass(frozen=True)
class CentralBankCommunicationRecord:
    source: str
    title: str
    url: str
    published_at: str
    content_type: str
    speaker: str = ""
    summary: str = ""
    full_text: str = ""


@dataclass(frozen=True)
class IndicatorObservationRecord:
    series_id: str
    source: str
    date: str
    value: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RegimeSnapshotRecord:
    snapshot_id: int
    timestamp: str
    regime_json: dict[str, Any]
    trigger_event: str
    summary: str


@dataclass(frozen=True)
class GeneratedNoteRecord:
    note_id: int
    created_at: str
    note_type: str
    title: str
    summary: str
    body_markdown: str
    regime_json: dict[str, Any] | None
    metadata: dict[str, Any]


class SQLiteEngineStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or default_engine_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    def get_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path))
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    @contextmanager
    def _connection(self, *, commit: bool) -> Iterator[sqlite3.Connection]:
        connection = self.get_connection()
        try:
            yield connection
            if commit:
                connection.commit()
        except Exception:
            if commit:
                connection.rollback()
            raise
        finally:
            connection.close()

    def init_schema(self) -> None:
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS calendar_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    datetime_utc TEXT NOT NULL,
                    country TEXT NOT NULL,
                    indicator TEXT NOT NULL,
                    category TEXT NOT NULL,
                    importance TEXT NOT NULL,
                    actual TEXT,
                    forecast TEXT,
                    previous TEXT,
                    revised_previous TEXT,
                    surprise REAL,
                    unit TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    scraped_at TEXT NOT NULL,
                    UNIQUE(source, event_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS market_prices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    asset_class TEXT NOT NULL,
                    name TEXT NOT NULL,
                    price REAL NOT NULL,
                    change_pct REAL,
                    datetime_utc TEXT NOT NULL,
                    scraped_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS central_bank_comms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    published_at TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    speaker TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    full_text TEXT NOT NULL,
                    scraped_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS indicators (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    series_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    date TEXT NOT NULL,
                    value REAL NOT NULL,
                    metadata_json TEXT NOT NULL,
                    scraped_at TEXT NOT NULL,
                    UNIQUE(series_id, source, date)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS regime_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    regime_json TEXT NOT NULL,
                    trigger_event TEXT NOT NULL,
                    summary TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS generated_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    note_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    body_markdown TEXT NOT NULL,
                    regime_json TEXT,
                    metadata_json TEXT NOT NULL
                )
                """
            )

    def upsert_calendar_event(self, event: StoredEventRecord) -> None:
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO calendar_events (
                    source,
                    event_id,
                    datetime_utc,
                    country,
                    indicator,
                    category,
                    importance,
                    actual,
                    forecast,
                    previous,
                    revised_previous,
                    surprise,
                    unit,
                    raw_json,
                    scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.source,
                    event.event_id,
                    event.datetime_utc,
                    event.country,
                    event.indicator,
                    event.category,
                    event.importance,
                    event.actual,
                    event.forecast,
                    event.previous,
                    event.revised_previous,
                    event.surprise,
                    event.unit,
                    json.dumps(event.raw_json, ensure_ascii=True, sort_keys=True),
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
                    datetime_utc,
                    scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    price.symbol,
                    price.asset_class,
                    price.name,
                    price.price,
                    price.change_pct,
                    price.datetime_utc,
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
                    published_at,
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
                    communication.published_at,
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
                    scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    observation.series_id,
                    observation.source,
                    observation.date,
                    observation.value,
                    json.dumps(observation.metadata, ensure_ascii=True, sort_keys=True),
                    utc_now().isoformat(),
                ),
            )

    def save_regime_snapshot(self, regime_json: dict[str, Any], trigger_event: str, summary: str) -> RegimeSnapshotRecord:
        timestamp = utc_now().isoformat()
        with self._connection(commit=True) as connection:
            cursor = connection.execute(
                """
                INSERT INTO regime_snapshots (
                    timestamp,
                    regime_json,
                    trigger_event,
                    summary
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    timestamp,
                    json.dumps(regime_json, ensure_ascii=True, sort_keys=True),
                    trigger_event,
                    summary,
                ),
            )
            snapshot_id = int(cursor.lastrowid)
        return RegimeSnapshotRecord(
            snapshot_id=snapshot_id,
            timestamp=timestamp,
            regime_json=regime_json,
            trigger_event=trigger_event,
            summary=summary,
        )

    def save_generated_note(
        self,
        note_type: str,
        title: str,
        summary: str,
        body_markdown: str,
        regime_json: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> GeneratedNoteRecord:
        created_at = utc_now().isoformat()
        with self._connection(commit=True) as connection:
            cursor = connection.execute(
                """
                INSERT INTO generated_notes (
                    created_at,
                    note_type,
                    title,
                    summary,
                    body_markdown,
                    regime_json,
                    metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    note_type,
                    title,
                    summary,
                    body_markdown,
                    json.dumps(regime_json, ensure_ascii=True, sort_keys=True) if regime_json else None,
                    json.dumps(metadata or {}, ensure_ascii=True, sort_keys=True),
                ),
            )
            note_id = int(cursor.lastrowid)
        return GeneratedNoteRecord(
            note_id=note_id,
            created_at=created_at,
            note_type=note_type,
            title=title,
            summary=summary,
            body_markdown=body_markdown,
            regime_json=regime_json,
            metadata=metadata or {},
        )

    def list_recent_events(
        self,
        *,
        limit: int = 10,
        days: int = 7,
        released_only: bool = False,
        importance: str | None = None,
    ) -> list[StoredEventRecord]:
        cutoff = (utc_now() - timedelta(days=days)).isoformat()
        conditions = ["datetime_utc >= ?"]
        params: list[Any] = [cutoff]
        if released_only:
            conditions.append("actual IS NOT NULL")
        if importance:
            conditions.append("importance = ?")
            params.append(importance)
        params.append(limit)
        # Only fixed SQL fragments are appended here; user input stays parameterized.
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM calendar_events
                WHERE {' AND '.join(conditions)}
                ORDER BY datetime_utc DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def list_upcoming_events(self, *, limit: int = 10) -> list[StoredEventRecord]:
        now_iso = utc_now().isoformat()
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT * FROM calendar_events
                WHERE datetime_utc >= ?
                ORDER BY datetime_utc ASC, id ASC
                LIMIT ?
                """,
                (now_iso, limit),
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
    ) -> list[CentralBankCommunicationRecord]:
        cutoff = (utc_now() - timedelta(days=days)).isoformat()
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT * FROM central_bank_comms
                WHERE source = ? AND published_at >= ?
                ORDER BY published_at DESC, id DESC
                LIMIT ?
                """,
                (source, cutoff, limit),
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

    def latest_regime_snapshot(self) -> RegimeSnapshotRecord | None:
        with self._connection(commit=False) as connection:
            row = connection.execute(
                """
                SELECT * FROM regime_snapshots
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return RegimeSnapshotRecord(
            snapshot_id=int(row["id"]),
            timestamp=row["timestamp"],
            regime_json=json.loads(row["regime_json"]),
            trigger_event=row["trigger_event"],
            summary=row["summary"],
        )

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
                ORDER BY importance DESC, datetime_utc DESC, id DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        return self._row_to_event(row) if row is not None else None

    def _row_to_event(self, row: sqlite3.Row) -> StoredEventRecord:
        return StoredEventRecord(
            source=row["source"],
            event_id=row["event_id"],
            datetime_utc=row["datetime_utc"],
            country=row["country"],
            indicator=row["indicator"],
            category=row["category"],
            importance=row["importance"],
            actual=row["actual"],
            forecast=row["forecast"],
            previous=row["previous"],
            revised_previous=row["revised_previous"],
            surprise=row["surprise"],
            unit=row["unit"],
            raw_json=json.loads(row["raw_json"]),
        )

    def _row_to_market_price(self, row: sqlite3.Row) -> MarketPriceRecord:
        return MarketPriceRecord(
            symbol=row["symbol"],
            asset_class=row["asset_class"],
            name=row["name"],
            price=float(row["price"]),
            change_pct=float(row["change_pct"]) if row["change_pct"] is not None else None,
            datetime_utc=row["datetime_utc"],
        )

    def _row_to_comm(self, row: sqlite3.Row) -> CentralBankCommunicationRecord:
        return CentralBankCommunicationRecord(
            source=row["source"],
            title=row["title"],
            url=row["url"],
            published_at=row["published_at"],
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
