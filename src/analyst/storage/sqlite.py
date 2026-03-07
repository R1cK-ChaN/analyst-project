from __future__ import annotations

from contextlib import contextmanager
import json
import math
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
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
    currency: str = ""
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
class NewsArticleRecord:
    url_hash: str
    source_feed: str
    feed_category: str
    title: str
    url: str
    published_at: str
    description: str
    content_markdown: str
    impact_level: str
    finance_category: str
    confidence: float
    content_fetched: bool
    institution: str = ""
    country: str = ""
    market: str = ""
    asset_class: str = ""
    sector: str = ""
    document_type: str = ""
    event_type: str = ""
    subject: str = ""
    subject_id: str = ""
    data_period: str = ""
    contains_commentary: bool = False
    language: str = "en"
    authors: str = ""
    extraction_provider: str = "keyword"


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


@dataclass(frozen=True)
class MemoryBlockRecord:
    name: str
    value: str
    updated_at: str
    label: str = ""
    description: str = ""


@dataclass(frozen=True)
class MemoryMessageRecord:
    role: str
    content: str
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryFactRecord:
    key: str
    value: Any
    confidence: float
    updated_at: str
    status: str = "active"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MemorySearchRecord:
    content: str
    score: float
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PublishedArtifactRecord:
    artifact_id: int
    artifact_type: str
    producer_agent: str
    title: str
    summary: str
    content_markdown: str
    created_at: str
    client_safe: bool
    source_scope_key: str
    payload: dict[str, Any]
    tags: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)


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
            try:
                connection.execute("ALTER TABLE calendar_events ADD COLUMN currency TEXT NOT NULL DEFAULT ''")
            except sqlite3.OperationalError:
                pass  # column already exists
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
                CREATE TABLE IF NOT EXISTS news_articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url_hash TEXT NOT NULL UNIQUE,
                    source_feed TEXT NOT NULL,
                    feed_category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    description TEXT NOT NULL,
                    content_markdown TEXT NOT NULL,
                    impact_level TEXT NOT NULL,
                    finance_category TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    content_fetched INTEGER NOT NULL DEFAULT 0,
                    scraped_at TEXT NOT NULL
                )
                """
            )
            # -- news_articles new columns for LLM extraction -----------
            _news_new_cols = [
                ("institution", "TEXT NOT NULL DEFAULT ''"),
                ("country", "TEXT NOT NULL DEFAULT ''"),
                ("market", "TEXT NOT NULL DEFAULT ''"),
                ("asset_class", "TEXT NOT NULL DEFAULT ''"),
                ("sector", "TEXT NOT NULL DEFAULT ''"),
                ("document_type", "TEXT NOT NULL DEFAULT ''"),
                ("event_type", "TEXT NOT NULL DEFAULT ''"),
                ("subject", "TEXT NOT NULL DEFAULT ''"),
                ("subject_id", "TEXT NOT NULL DEFAULT ''"),
                ("data_period", "TEXT NOT NULL DEFAULT ''"),
                ("contains_commentary", "INTEGER NOT NULL DEFAULT 0"),
                ("language", "TEXT NOT NULL DEFAULT 'en'"),
                ("authors", "TEXT NOT NULL DEFAULT ''"),
                ("extraction_provider", "TEXT NOT NULL DEFAULT 'keyword'"),
            ]
            for col_name, col_def in _news_new_cols:
                try:
                    connection.execute(f"ALTER TABLE news_articles ADD COLUMN {col_name} {col_def}")
                except sqlite3.OperationalError:
                    pass
            # Repair rows written by older builds that truncated published_at
            # to a bare date. Prefer the original scraped_at when it shares
            # the same day; otherwise normalize to midnight UTC.
            connection.execute(
                """
                UPDATE news_articles
                SET published_at = CASE
                    WHEN substr(scraped_at, 1, 10) = published_at THEN scraped_at
                    ELSE published_at || 'T00:00:00+00:00'
                END
                WHERE length(published_at) = 10
                  AND published_at LIKE '____-__-__'
                """
            )
            # -- FTS5 full-text search for news articles ----------------
            # Guarded: SQLite builds without FTS5 skip this block;
            # search_news() falls back to LIKE queries.
            try:
                connection.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS news_fts USING fts5(
                        title, description, subject,
                        content='news_articles',
                        content_rowid='id'
                    )
                    """
                )
                for trigger_name in ("news_fts_ai", "news_fts_ad", "news_fts_au"):
                    connection.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")
                connection.execute(
                    """
                    CREATE TRIGGER news_fts_ai AFTER INSERT ON news_articles BEGIN
                        INSERT INTO news_fts(rowid, title, description, subject)
                        VALUES (new.id, new.title, new.description, new.subject);
                    END
                    """
                )
                connection.execute(
                    """
                    CREATE TRIGGER news_fts_ad AFTER DELETE ON news_articles BEGIN
                        INSERT INTO news_fts(news_fts, rowid, title, description, subject)
                        VALUES ('delete', old.id, old.title, old.description, old.subject);
                    END
                    """
                )
                connection.execute(
                    """
                    CREATE TRIGGER news_fts_au AFTER UPDATE ON news_articles BEGIN
                        INSERT INTO news_fts(news_fts, rowid, title, description, subject)
                        VALUES ('delete', old.id, old.title, old.description, old.subject);
                        INSERT INTO news_fts(rowid, title, description, subject)
                        VALUES (new.id, new.title, new.description, new.subject);
                    END
                    """
                )
                connection.execute("INSERT INTO news_fts(news_fts) VALUES('rebuild')")
            except sqlite3.OperationalError:
                pass  # FTS5 not available; search_news() will use LIKE fallback
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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_scopes (
                    scope_key TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    agent_kind TEXT NOT NULL,
                    visibility TEXT NOT NULL,
                    scope_kind TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    subject_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_blocks (
                    scope_key TEXT NOT NULL,
                    block_name TEXT NOT NULL,
                    value TEXT NOT NULL,
                    label TEXT NOT NULL,
                    description TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (scope_key, block_name),
                    FOREIGN KEY (scope_key) REFERENCES memory_scopes(scope_key)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope_key TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (scope_key) REFERENCES memory_scopes(scope_key)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope_key TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (scope_key) REFERENCES memory_scopes(scope_key)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope_key TEXT NOT NULL,
                    fact_key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(scope_key, fact_key),
                    FOREIGN KEY (scope_key) REFERENCES memory_scopes(scope_key)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_archival (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope_key TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (scope_key) REFERENCES memory_scopes(scope_key)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS published_artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    artifact_type TEXT NOT NULL,
                    producer_agent TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    content_markdown TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    source_scope_key TEXT NOT NULL,
                    client_safe INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS interaction_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_scope_key TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    user_text TEXT NOT NULL,
                    assistant_text TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_messages_scope_created ON memory_messages(scope_key, id DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_events_scope_created ON memory_events(scope_key, id DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_archival_scope_created ON memory_archival(scope_key, id DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_interaction_logs_scope_created ON interaction_logs(client_scope_key, id DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_published_artifacts_safe_type_created ON published_artifacts(client_safe, artifact_type, id DESC)"
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
                    currency,
                    unit,
                    raw_json,
                    scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    event.currency,
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
        country: str | None = None,
        category: str | None = None,
    ) -> list[StoredEventRecord]:
        cutoff = (utc_now() - timedelta(days=days)).isoformat()
        conditions = ["datetime_utc >= ?"]
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
                ORDER BY datetime_utc DESC, id DESC
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
        now_iso = utc_now().isoformat()
        conditions = ["datetime_utc >= ?"]
        params: list[Any] = [now_iso]
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
                ORDER BY datetime_utc ASC, id ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def list_events_in_range(
        self,
        *,
        date_from: str,
        date_to: str,
        limit: int = 50,
        importance: str | None = None,
        country: str | None = None,
        category: str | None = None,
        released_only: bool = False,
    ) -> list[StoredEventRecord]:
        conditions = ["datetime_utc >= ?", "datetime_utc <= ?"]
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
                ORDER BY datetime_utc ASC, id ASC
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
        date_from = datetime(today.year, today.month, today.day, tzinfo=timezone.utc).isoformat()
        date_to = datetime(today.year, today.month, today.day, 23, 59, 59, tzinfo=timezone.utc).isoformat()
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
                ORDER BY datetime_utc DESC, id DESC
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
            currency=row["currency"],
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

    # -- News articles -------------------------------------------------------

    # Time-decay constants for news retrieval scoring
    _IMPACT_HALF_LIFE = {"critical": 7, "high": 5, "medium": 3, "low": 2, "info": 1}
    _IMPACT_WEIGHT = {"critical": 2.0, "high": 1.5, "medium": 1.0, "low": 0.6, "info": 0.3}
    _TIME_DECAY_MAX_BOOST = 1.5
    _TIME_DECAY_MIN_BOOST = 0.1

    @staticmethod
    def _normalize_news_published_at(published_at: str) -> str:
        if not published_at:
            return published_at
        try:
            parsed = datetime.fromisoformat(published_at)
        except ValueError:
            return published_at
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.isoformat()

    @staticmethod
    def _parse_news_published_at(published_at: str) -> datetime:
        parsed = datetime.fromisoformat(published_at)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    def upsert_news_article(self, article: NewsArticleRecord) -> None:
        normalized_published_at = self._normalize_news_published_at(article.published_at)
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO news_articles (
                    url_hash, source_feed, feed_category, title, url,
                    published_at, description, content_markdown,
                    impact_level, finance_category, confidence,
                    content_fetched, institution, country, market,
                    asset_class, sector, document_type, event_type,
                    subject, subject_id, data_period,
                    contains_commentary, language, authors,
                    extraction_provider, scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    article.url_hash,
                    article.source_feed,
                    article.feed_category,
                    article.title,
                    article.url,
                    normalized_published_at,
                    article.description,
                    article.content_markdown,
                    article.impact_level,
                    article.finance_category,
                    article.confidence,
                    int(article.content_fetched),
                    article.institution,
                    article.country,
                    article.market,
                    article.asset_class,
                    article.sector,
                    article.document_type,
                    article.event_type,
                    article.subject,
                    article.subject_id,
                    article.data_period,
                    int(article.contains_commentary),
                    article.language,
                    article.authors,
                    article.extraction_provider,
                    utc_now().isoformat(),
                ),
            )

    def list_recent_news(
        self,
        *,
        limit: int = 20,
        days: int = 7,
        impact_level: str | None = None,
        feed_category: str | None = None,
        finance_category: str | None = None,
        country: str | None = None,
        asset_class: str | None = None,
    ) -> list[NewsArticleRecord]:
        cutoff = (utc_now() - timedelta(days=days)).isoformat()
        conditions = ["published_at >= ?"]
        params: list[Any] = [cutoff]
        if impact_level:
            conditions.append("impact_level = ?")
            params.append(impact_level)
        if feed_category:
            conditions.append("feed_category = ?")
            params.append(feed_category)
        if finance_category:
            conditions.append("finance_category = ?")
            params.append(finance_category)
        if country:
            conditions.append("country = ?")
            params.append(country)
        if asset_class:
            conditions.append("asset_class = ?")
            params.append(asset_class)
        params.append(limit)
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM news_articles
                WHERE {' AND '.join(conditions)}
                ORDER BY published_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_news_article(row) for row in rows]

    def search_news(self, query: str, *, limit: int = 20) -> list[NewsArticleRecord]:
        with self._connection(commit=False) as connection:
            try:
                rows = connection.execute(
                    """
                    SELECT n.* FROM news_articles n
                    JOIN news_fts ON news_fts.rowid = n.id
                    WHERE news_fts MATCH ?
                    ORDER BY n.published_at DESC, n.id DESC
                    LIMIT ?
                    """,
                    (query, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                pattern = f"%{query}%"
                rows = connection.execute(
                    """
                    SELECT * FROM news_articles
                    WHERE title LIKE ? OR description LIKE ?
                    ORDER BY published_at DESC, id DESC
                    LIMIT ?
                    """,
                    (pattern, pattern, limit),
                ).fetchall()
        return [self._row_to_news_article(row) for row in rows]

    def get_news_context(
        self,
        *,
        query: str | None = None,
        days: int = 7,
        limit: int = 15,
        impact_level: str | None = None,
        feed_category: str | None = None,
        finance_category: str | None = None,
        country: str | None = None,
        asset_class: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve news with time-decay + impact-weight composite scoring."""
        cutoff = (utc_now() - timedelta(days=days)).isoformat()
        conditions = ["published_at >= ?"]
        params: list[Any] = [cutoff]
        if impact_level:
            conditions.append("impact_level = ?")
            params.append(impact_level)
        if feed_category:
            conditions.append("feed_category = ?")
            params.append(feed_category)
        if finance_category:
            conditions.append("finance_category = ?")
            params.append(finance_category)
        if country:
            conditions.append("country = ?")
            params.append(country)
        if asset_class:
            conditions.append("asset_class = ?")
            params.append(asset_class)

        with self._connection(commit=False) as connection:
            if query:
                try:
                    rows = connection.execute(
                        f"""
                        SELECT n.* FROM news_articles n
                        JOIN news_fts ON news_fts.rowid = n.id
                        WHERE news_fts MATCH ? AND {' AND '.join(conditions)}
                        """,
                        [query] + params,
                    ).fetchall()
                except sqlite3.OperationalError:
                    pattern = f"%{query}%"
                    conditions.append("(title LIKE ? OR description LIKE ?)")
                    params.extend([pattern, pattern])
                    rows = connection.execute(
                        f"""
                        SELECT * FROM news_articles
                        WHERE {' AND '.join(conditions)}
                        """,
                        params,
                    ).fetchall()
            else:
                rows = connection.execute(
                    f"""
                    SELECT * FROM news_articles
                    WHERE {' AND '.join(conditions)}
                    """,
                    params,
                ).fetchall()

        now = utc_now()
        scored: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            article = self._row_to_news_article(row)
            try:
                pub = self._parse_news_published_at(article.published_at)
                age_days = max((now - pub).total_seconds() / 86400, 0.0)
            except (ValueError, TypeError):
                age_days = float(days)
            half_life = self._IMPACT_HALF_LIFE.get(article.impact_level, 2)
            time_decay = self._TIME_DECAY_MIN_BOOST + (
                (self._TIME_DECAY_MAX_BOOST - self._TIME_DECAY_MIN_BOOST)
                * math.pow(2, -age_days / half_life)
            )
            impact_w = self._IMPACT_WEIGHT.get(article.impact_level, 0.5)
            composite = time_decay * impact_w

            desc = article.description
            if len(desc) > 500:
                desc = desc[:500] + "..."
            scored.append((composite, {
                "source_feed": article.source_feed,
                "title": article.title,
                "url": article.url,
                "published_at": article.published_at,
                "description": desc,
                "impact_level": article.impact_level,
                "finance_category": article.finance_category,
                "country": article.country,
                "asset_class": article.asset_class,
                "subject": article.subject,
                "event_type": article.event_type,
                "score": round(composite, 4),
            }))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:limit]]

    def get_recent_news_titles(self, *, hours: int = 24) -> list[str]:
        cutoff = (utc_now() - timedelta(hours=hours)).isoformat()
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT title FROM news_articles
                WHERE scraped_at >= ?
                ORDER BY id DESC
                """,
                (cutoff,),
            ).fetchall()
        return [row["title"] for row in rows]

    def news_article_exists(self, url_hash: str) -> bool:
        with self._connection(commit=False) as connection:
            row = connection.execute(
                "SELECT 1 FROM news_articles WHERE url_hash = ? LIMIT 1",
                (url_hash,),
            ).fetchone()
        return row is not None

    def _row_to_news_article(self, row: sqlite3.Row) -> NewsArticleRecord:
        return NewsArticleRecord(
            url_hash=row["url_hash"],
            source_feed=row["source_feed"],
            feed_category=row["feed_category"],
            title=row["title"],
            url=row["url"],
            published_at=row["published_at"],
            description=row["description"],
            content_markdown=row["content_markdown"],
            impact_level=row["impact_level"],
            finance_category=row["finance_category"],
            confidence=float(row["confidence"]),
            content_fetched=bool(row["content_fetched"]),
            institution=row["institution"] or "",
            country=row["country"] or "",
            market=row["market"] or "",
            asset_class=row["asset_class"] or "",
            sector=row["sector"] or "",
            document_type=row["document_type"] or "",
            event_type=row["event_type"] or "",
            subject=row["subject"] or "",
            subject_id=row["subject_id"] or "",
            data_period=row["data_period"] or "",
            contains_commentary=bool(row["contains_commentary"]),
            language=row["language"] or "en",
            authors=row["authors"] or "",
            extraction_provider=row["extraction_provider"] or "keyword",
        )

    # -- Memory and published artifact stores -------------------------------

    def ensure_memory_scope(self, scope: Any) -> None:
        with self._connection(commit=True) as connection:
            self._ensure_memory_scope_in_connection(connection, scope)

    def upsert_memory_block(
        self,
        scope: Any,
        *,
        name: str,
        value: str,
        label: str = "",
        description: str = "",
    ) -> None:
        self.ensure_memory_scope(scope)
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                INSERT INTO memory_blocks (
                    scope_key,
                    block_name,
                    value,
                    label,
                    description,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(scope_key, block_name) DO UPDATE SET
                    value = excluded.value,
                    label = excluded.label,
                    description = excluded.description,
                    updated_at = excluded.updated_at
                """,
                (
                    self._scope_key(scope),
                    name,
                    value,
                    label,
                    description,
                    utc_now().isoformat(),
                ),
            )

    def list_memory_blocks(self, scope: Any) -> list[MemoryBlockRecord]:
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT * FROM memory_blocks
                WHERE scope_key = ?
                ORDER BY updated_at ASC, block_name ASC
                """,
                (self._scope_key(scope),),
            ).fetchall()
        return [
            MemoryBlockRecord(
                name=row["block_name"],
                value=row["value"],
                updated_at=row["updated_at"],
                label=row["label"],
                description=row["description"],
            )
            for row in rows
        ]

    def append_memory_message(
        self,
        scope: Any,
        *,
        role: str,
        content: str,
        metadata: dict[str, Any],
    ) -> None:
        self.ensure_memory_scope(scope)
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                INSERT INTO memory_messages (
                    scope_key,
                    role,
                    content,
                    metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    self._scope_key(scope),
                    role,
                    content,
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    utc_now().isoformat(),
                ),
            )

    def list_memory_messages(self, scope: Any, *, limit: int = 24) -> list[MemoryMessageRecord]:
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT * FROM memory_messages
                WHERE scope_key = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (self._scope_key(scope), limit),
            ).fetchall()
        records = [
            MemoryMessageRecord(
                role=row["role"],
                content=row["content"],
                created_at=row["created_at"],
                metadata=json.loads(row["metadata_json"]),
            )
            for row in rows
        ]
        records.reverse()
        return records

    def append_memory_event(self, scope: Any, *, event_type: str, data: dict[str, Any]) -> None:
        self.ensure_memory_scope(scope)
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                INSERT INTO memory_events (
                    scope_key,
                    event_type,
                    data_json,
                    created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    self._scope_key(scope),
                    event_type,
                    json.dumps(data, ensure_ascii=False, sort_keys=True),
                    utc_now().isoformat(),
                ),
            )

    def upsert_memory_fact(
        self,
        scope: Any,
        *,
        fact_key: str,
        value: Any,
        confidence: float,
        metadata: dict[str, Any],
        status: str = "active",
    ) -> None:
        self.ensure_memory_scope(scope)
        with self._connection(commit=True) as connection:
            self._upsert_memory_fact_in_connection(
                connection,
                scope_key=self._scope_key(scope),
                fact_key=fact_key,
                value=value,
                confidence=confidence,
                status=status,
                metadata=metadata,
            )

    def list_memory_facts(self, scope: Any) -> list[MemoryFactRecord]:
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT * FROM memory_facts
                WHERE scope_key = ? AND status = 'active'
                ORDER BY confidence DESC, updated_at DESC
                """,
                (self._scope_key(scope),),
            ).fetchall()
        return [
            MemoryFactRecord(
                key=row["fact_key"],
                value=json.loads(row["value_json"]),
                confidence=float(row["confidence"]),
                updated_at=row["updated_at"],
                status=row["status"],
                metadata=json.loads(row["metadata_json"]),
            )
            for row in rows
        ]

    def insert_memory_archival(self, scope: Any, *, content: str, metadata: dict[str, Any]) -> None:
        self.ensure_memory_scope(scope)
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                INSERT INTO memory_archival (
                    scope_key,
                    content,
                    metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    self._scope_key(scope),
                    content,
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    utc_now().isoformat(),
                ),
            )

    def search_memory_archival(
        self,
        scope: Any,
        *,
        query: str,
        limit: int = 3,
    ) -> list[MemorySearchRecord]:
        terms = self._search_terms(query)
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT * FROM memory_archival
                WHERE scope_key = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (self._scope_key(scope), max(limit * 20, 100)),
            ).fetchall()
        scored: list[tuple[float, MemorySearchRecord]] = []
        for row in rows:
            content = row["content"]
            score = self._score_text_match(content, terms)
            if score <= 0:
                continue
            scored.append(
                (
                    score,
                    MemorySearchRecord(
                        content=content,
                        score=score,
                        created_at=row["created_at"],
                        metadata=json.loads(row["metadata_json"]),
                    ),
                )
            )
        scored.sort(key=lambda item: (item[0], item[1].created_at), reverse=True)
        return [record for _, record in scored[:limit]]

    def publish_artifact(
        self,
        *,
        artifact_type: str,
        producer_agent: str,
        title: str,
        summary: str,
        content_markdown: str,
        payload: dict[str, Any],
        tags: list[str],
        source_scope_key: str,
        client_safe: bool,
        metadata: dict[str, Any] | None = None,
    ) -> PublishedArtifactRecord:
        created_at = utc_now().isoformat()
        with self._connection(commit=True) as connection:
            cursor = connection.execute(
                """
                INSERT INTO published_artifacts (
                    artifact_type,
                    producer_agent,
                    title,
                    summary,
                    content_markdown,
                    payload_json,
                    tags_json,
                    metadata_json,
                    source_scope_key,
                    client_safe,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_type,
                    producer_agent,
                    title,
                    summary,
                    content_markdown,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    json.dumps(tags, ensure_ascii=False, sort_keys=True),
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                    source_scope_key,
                    int(client_safe),
                    created_at,
                ),
            )
            artifact_id = int(cursor.lastrowid)
        return PublishedArtifactRecord(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            producer_agent=producer_agent,
            title=title,
            summary=summary,
            content_markdown=content_markdown,
            created_at=created_at,
            client_safe=client_safe,
            source_scope_key=source_scope_key,
            payload=payload,
            tags=tags,
            metadata=metadata or {},
        )

    def search_published_artifacts(
        self,
        *,
        query: str,
        limit: int = 5,
        client_safe_only: bool = True,
        artifact_types: tuple[str, ...] = (),
    ) -> list[PublishedArtifactRecord]:
        terms = self._search_terms(query)
        conditions: list[str] = []
        params: list[Any] = []
        if client_safe_only:
            conditions.append("client_safe = 1")
        if artifact_types:
            conditions.append("artifact_type IN (" + ",".join("?" for _ in artifact_types) + ")")
            params.extend(artifact_types)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT * FROM published_artifacts
                {where_clause}
                ORDER BY id DESC
                LIMIT ?
                """.format(where_clause=where_clause),
                [*params, max(limit * 20, 200)],
            ).fetchall()
        scored: list[tuple[float, PublishedArtifactRecord]] = []
        for row in rows:
            haystack = " ".join([row["title"], row["summary"], row["content_markdown"]])
            score = self._score_text_match(haystack, terms)
            if score <= 0:
                continue
            scored.append((score, self._row_to_published_artifact(row, score)))
        scored.sort(key=lambda item: (item[0], item[1].created_at), reverse=True)
        return [record for _, record in scored[:limit]]

    def append_interaction_log(
        self,
        *,
        client_scope_key: str,
        channel: str,
        thread_id: str,
        user_text: str,
        assistant_text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                INSERT INTO interaction_logs (
                    client_scope_key,
                    channel,
                    thread_id,
                    user_text,
                    assistant_text,
                    metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    client_scope_key,
                    channel,
                    thread_id,
                    user_text,
                    assistant_text,
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                    utc_now().isoformat(),
                ),
            )

    def record_sales_memory_turn(
        self,
        *,
        client_scope: Any,
        thread_scope: Any,
        channel: str,
        thread_id: str,
        user_text: str,
        assistant_text: str,
        fact_updates: list[dict[str, Any]],
    ) -> None:
        client_scope_key = self._scope_key(client_scope)
        thread_scope_key = self._scope_key(thread_scope)
        combined_length = len(user_text) + len(assistant_text)
        with self._connection(commit=True) as connection:
            self._ensure_memory_scope_in_connection(connection, client_scope)
            self._ensure_memory_scope_in_connection(connection, thread_scope)
            timestamp = utc_now().isoformat()
            connection.executemany(
                """
                INSERT INTO memory_messages (
                    scope_key,
                    role,
                    content,
                    metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        thread_scope_key,
                        "user",
                        user_text,
                        json.dumps({"channel": channel}, ensure_ascii=False, sort_keys=True),
                        timestamp,
                    ),
                    (
                        thread_scope_key,
                        "assistant",
                        assistant_text,
                        json.dumps({"channel": channel}, ensure_ascii=False, sort_keys=True),
                        timestamp,
                    ),
                ],
            )
            connection.execute(
                """
                INSERT INTO memory_events (
                    scope_key,
                    event_type,
                    data_json,
                    created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    thread_scope_key,
                    "message_turn",
                    json.dumps({"channel": channel, "thread_id": thread_id}, ensure_ascii=False, sort_keys=True),
                    timestamp,
                ),
            )
            for update in fact_updates:
                self._upsert_memory_fact_in_connection(
                    connection,
                    scope_key=client_scope_key,
                    fact_key=str(update["key"]),
                    value=update["value"],
                    confidence=float(update["confidence"]),
                    status="active",
                    metadata=dict(update.get("metadata", {})),
                )
            if fact_updates or combined_length >= 80:
                connection.execute(
                    """
                    INSERT INTO memory_archival (
                        scope_key,
                        content,
                        metadata_json,
                        created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        client_scope_key,
                        f"User: {user_text}\nAssistant: {assistant_text}",
                        json.dumps(
                            {"channel": channel, "thread_id": thread_id, "source": "sales_turn"},
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        timestamp,
                    ),
                )
            connection.execute(
                """
                INSERT INTO interaction_logs (
                    client_scope_key,
                    channel,
                    thread_id,
                    user_text,
                    assistant_text,
                    metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    client_scope_key,
                    channel,
                    thread_id,
                    user_text,
                    assistant_text,
                    json.dumps({"agent": "sales"}, ensure_ascii=False, sort_keys=True),
                    timestamp,
                ),
            )

    def _row_to_published_artifact(self, row: sqlite3.Row, score: float | None = None) -> PublishedArtifactRecord:
        metadata = json.loads(row["metadata_json"])
        if score is not None:
            metadata = {**metadata, "score": score}
        return PublishedArtifactRecord(
            artifact_id=int(row["id"]),
            artifact_type=row["artifact_type"],
            producer_agent=row["producer_agent"],
            title=row["title"],
            summary=row["summary"],
            content_markdown=row["content_markdown"],
            created_at=row["created_at"],
            client_safe=bool(row["client_safe"]),
            source_scope_key=row["source_scope_key"],
            payload=json.loads(row["payload_json"]),
            tags=json.loads(row["tags_json"]),
            metadata=metadata,
        )

    def _scope_key(self, scope: Any) -> str:
        if hasattr(scope, "storage_key"):
            return str(scope.storage_key())
        return str(scope)

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

    def _ensure_memory_scope_in_connection(self, connection: sqlite3.Connection, scope: Any) -> None:
        scope_key = self._scope_key(scope)
        timestamp = utc_now().isoformat()
        connection.execute(
            """
            INSERT INTO memory_scopes (
                scope_key,
                tenant_id,
                agent_kind,
                visibility,
                scope_kind,
                scope_id,
                subject_id,
                thread_id,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(scope_key) DO UPDATE SET
                updated_at = excluded.updated_at
            """,
            (
                scope_key,
                getattr(scope, "tenant_id", "default"),
                getattr(getattr(scope, "agent_kind", None), "value", getattr(scope, "agent_kind", "")),
                getattr(getattr(scope, "visibility", None), "value", getattr(scope, "visibility", "")),
                getattr(getattr(scope, "scope_kind", None), "value", getattr(scope, "scope_kind", "")),
                getattr(scope, "scope_id", ""),
                getattr(scope, "subject_id", ""),
                getattr(scope, "thread_id", ""),
                timestamp,
                timestamp,
            ),
        )

    def _upsert_memory_fact_in_connection(
        self,
        connection: sqlite3.Connection,
        *,
        scope_key: str,
        fact_key: str,
        value: Any,
        confidence: float,
        status: str,
        metadata: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO memory_facts (
                scope_key,
                fact_key,
                value_json,
                confidence,
                status,
                metadata_json,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(scope_key, fact_key) DO UPDATE SET
                value_json = excluded.value_json,
                confidence = excluded.confidence,
                status = excluded.status,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            WHERE excluded.confidence >= memory_facts.confidence
              AND (
                  excluded.value_json <> memory_facts.value_json
                  OR excluded.confidence <> memory_facts.confidence
                  OR excluded.status <> memory_facts.status
                  OR excluded.metadata_json <> memory_facts.metadata_json
              )
            """,
            (
                scope_key,
                fact_key,
                json.dumps(value, ensure_ascii=False, sort_keys=True),
                confidence,
                status,
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                utc_now().isoformat(),
            ),
        )
