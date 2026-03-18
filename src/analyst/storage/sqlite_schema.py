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

class SQLiteSchemaMixin:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or default_engine_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    def get_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path))
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
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
                    timestamp INTEGER NOT NULL,
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
                    timestamp INTEGER NOT NULL,
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
                    timestamp INTEGER NOT NULL,
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
                CREATE TABLE IF NOT EXISTS indicator_vintages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    series_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    observation_date TEXT NOT NULL,
                    vintage_date TEXT NOT NULL,
                    value REAL NOT NULL,
                    metadata_json TEXT NOT NULL,
                    scraped_at TEXT NOT NULL,
                    UNIQUE(series_id, source, observation_date, vintage_date)
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
                    timestamp INTEGER NOT NULL,
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
            # -- Article fingerprint table for multi-layer dedup ----------
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS article_fingerprint (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url_hash TEXT NOT NULL,
                    title_hash TEXT NOT NULL,
                    canonical_url TEXT NOT NULL,
                    raw_url TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    source_feed TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_fp_url ON article_fingerprint(url_hash)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_fp_title ON article_fingerprint(title_hash)"
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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS analytical_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    observation_type TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_id INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS research_artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    artifact_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    content_markdown TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_id INTEGER NOT NULL,
                    tags_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS trade_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    rationale_markdown TEXT NOT NULL,
                    signal_json TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS decision_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    decision_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    rationale_markdown TEXT NOT NULL,
                    research_artifact_id INTEGER,
                    signal_id INTEGER,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (research_artifact_id) REFERENCES research_artifacts(id),
                    FOREIGN KEY (signal_id) REFERENCES trade_signals(id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS position_state (
                    symbol TEXT PRIMARY KEY,
                    exposure REAL NOT NULL,
                    direction TEXT NOT NULL,
                    thesis TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS performance_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    metric_name TEXT NOT NULL,
                    metric_value REAL NOT NULL,
                    period_label TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS trading_artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    artifact_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    rationale_markdown TEXT NOT NULL,
                    research_artifact_id INTEGER NOT NULL,
                    decision_log_id INTEGER,
                    signal_json TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    tags_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (research_artifact_id) REFERENCES research_artifacts(id),
                    FOREIGN KEY (decision_log_id) REFERENCES decision_log(id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS client_profiles (
                    client_id TEXT PRIMARY KEY,
                    preferred_language TEXT NOT NULL DEFAULT '',
                    watchlist_topics_json TEXT NOT NULL DEFAULT '[]',
                    response_style TEXT NOT NULL DEFAULT '',
                    risk_appetite TEXT NOT NULL DEFAULT '',
                    investment_horizon TEXT NOT NULL DEFAULT '',
                    institution_type TEXT NOT NULL DEFAULT '',
                    risk_preference TEXT NOT NULL DEFAULT '',
                    asset_focus_json TEXT NOT NULL DEFAULT '[]',
                    market_focus_json TEXT NOT NULL DEFAULT '[]',
                    expertise_level TEXT NOT NULL DEFAULT '',
                    activity TEXT NOT NULL DEFAULT '',
                    current_mood TEXT NOT NULL DEFAULT '',
                    confidence TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    last_active_at TEXT NOT NULL DEFAULT '',
                    total_interactions INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._ensure_table_columns(
                connection,
                table_name="client_profiles",
                columns={
                    "institution_type": "TEXT NOT NULL DEFAULT ''",
                    "risk_preference": "TEXT NOT NULL DEFAULT ''",
                    "asset_focus_json": "TEXT NOT NULL DEFAULT '[]'",
                    "market_focus_json": "TEXT NOT NULL DEFAULT '[]'",
                    "expertise_level": "TEXT NOT NULL DEFAULT ''",
                    "activity": "TEXT NOT NULL DEFAULT ''",
                    "current_mood": "TEXT NOT NULL DEFAULT ''",
                    "emotional_trend": "TEXT NOT NULL DEFAULT ''",
                    "stress_level": "TEXT NOT NULL DEFAULT ''",
                    "confidence": "TEXT NOT NULL DEFAULT ''",
                    "notes": "TEXT NOT NULL DEFAULT ''",
                    "personal_facts_json": "TEXT NOT NULL DEFAULT '[]'",
                },
            )
            self._ensure_table_columns(
                connection,
                table_name="client_profiles",
                columns={
                    "timezone_name": "TEXT NOT NULL DEFAULT 'Asia/Shanghai'",
                },
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_threads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    opened_at TEXT NOT NULL,
                    last_active_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    UNIQUE(client_id, channel, thread_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (client_id, channel, thread_id)
                        REFERENCES conversation_threads(client_id, channel, thread_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS delivery_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_artifact_id INTEGER,
                    content_rendered TEXT NOT NULL,
                    status TEXT NOT NULL,
                    delivered_at TEXT,
                    client_reaction TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS companion_checkin_state (
                    client_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    pending_kind TEXT NOT NULL DEFAULT '',
                    pending_due_at TEXT NOT NULL DEFAULT '',
                    last_sent_at TEXT NOT NULL DEFAULT '',
                    last_sent_kind TEXT NOT NULL DEFAULT '',
                    cooldown_until TEXT NOT NULL DEFAULT '',
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (client_id, channel, thread_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS companion_lifestyle_state (
                    client_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    timezone_name TEXT NOT NULL DEFAULT 'Asia/Singapore',
                    home_base TEXT NOT NULL DEFAULT 'Singapore',
                    work_area TEXT NOT NULL DEFAULT 'Tanjong Pagar',
                    routine_state TEXT NOT NULL DEFAULT '',
                    last_state_changed_at TEXT NOT NULL DEFAULT '',
                    last_morning_checkin_at TEXT NOT NULL DEFAULT '',
                    last_evening_checkin_at TEXT NOT NULL DEFAULT '',
                    last_weekend_checkin_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (client_id, channel, thread_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS companion_daily_schedule (
                    schedule_date TEXT PRIMARY KEY,
                    timezone_name TEXT NOT NULL DEFAULT 'Asia/Singapore',
                    routine_state_snapshot TEXT NOT NULL DEFAULT '',
                    morning_plan TEXT NOT NULL DEFAULT '',
                    lunch_plan TEXT NOT NULL DEFAULT '',
                    afternoon_plan TEXT NOT NULL DEFAULT '',
                    dinner_plan TEXT NOT NULL DEFAULT '',
                    evening_plan TEXT NOT NULL DEFAULT '',
                    current_plan TEXT NOT NULL DEFAULT '',
                    next_plan TEXT NOT NULL DEFAULT '',
                    revision_note TEXT NOT NULL DEFAULT '',
                    last_explicit_update_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS companion_reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    reminder_text TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    timezone_name TEXT NOT NULL DEFAULT 'Asia/Singapore',
                    status TEXT NOT NULL DEFAULT 'pending',
                    sent_at TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (client_id, channel, thread_id)
                        REFERENCES conversation_threads(client_id, channel, thread_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS companion_relationship_state (
                    client_id TEXT PRIMARY KEY,
                    intimacy_level REAL NOT NULL DEFAULT 0.0,
                    relationship_stage TEXT NOT NULL DEFAULT 'stranger',
                    tendency_friend REAL NOT NULL DEFAULT 0.25,
                    tendency_romantic REAL NOT NULL DEFAULT 0.25,
                    tendency_confidant REAL NOT NULL DEFAULT 0.25,
                    tendency_mentor REAL NOT NULL DEFAULT 0.25,
                    streak_days INTEGER NOT NULL DEFAULT 0,
                    total_turns INTEGER NOT NULL DEFAULT 0,
                    avg_session_turns REAL NOT NULL DEFAULT 0.0,
                    mood_history_json TEXT NOT NULL DEFAULT '[]',
                    nicknames_json TEXT NOT NULL DEFAULT '[]',
                    previous_stage TEXT NOT NULL DEFAULT '',
                    last_interaction_date TEXT NOT NULL DEFAULT '',
                    last_stage_transition_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._ensure_table_columns(
                connection,
                table_name="companion_relationship_state",
                columns={
                    "previous_stage": "TEXT NOT NULL DEFAULT ''",
                    "outreach_paused": "INTEGER NOT NULL DEFAULT 0",
                    "outreach_paused_at": "TEXT NOT NULL DEFAULT ''",
                    "peak_intimacy_level": "REAL NOT NULL DEFAULT 0.0",
                    "tendency_damping_json": "TEXT NOT NULL DEFAULT '{}'",
                },
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS companion_outreach_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT '',
                    content_raw TEXT NOT NULL,
                    content_normalized TEXT NOT NULL,
                    sent_at TEXT NOT NULL,
                    user_replied INTEGER NOT NULL DEFAULT 0,
                    user_replied_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_outreach_log_client_sent ON companion_outreach_log(client_id, sent_at)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS companion_image_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    scene_key TEXT NOT NULL DEFAULT '',
                    trigger_type TEXT NOT NULL,
                    outreach_kind TEXT NOT NULL DEFAULT '',
                    relationship_stage TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    scene_override INTEGER NOT NULL DEFAULT 0,
                    blocked INTEGER NOT NULL DEFAULT 0,
                    block_reason TEXT NOT NULL DEFAULT ''
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_image_log_client_date ON companion_image_log(client_id, generated_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_analytical_observations_created ON analytical_observations(id DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_research_artifacts_type_created ON research_artifacts(artifact_type, id DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_trading_artifacts_research_created ON trading_artifacts(research_artifact_id, id DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_decision_log_research_created ON decision_log(research_artifact_id, id DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_performance_records_metric_created ON performance_records(metric_name, id DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_conversation_messages_thread_created ON conversation_messages(client_id, channel, thread_id, id DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_delivery_queue_client_created ON delivery_queue(client_id, channel, thread_id, id DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_companion_checkin_due ON companion_checkin_state(enabled, pending_due_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_companion_reminders_due ON companion_reminders(status, due_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_companion_lifestyle_updated ON companion_lifestyle_state(updated_at DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_companion_daily_schedule_updated ON companion_daily_schedule(updated_at DESC)"
            )
            # -- Portfolio volatility management tables ---------------------
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS portfolio_holdings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    portfolio_id TEXT NOT NULL DEFAULT 'default',
                    symbol TEXT NOT NULL,
                    name TEXT NOT NULL,
                    asset_class TEXT NOT NULL,
                    weight REAL NOT NULL,
                    notional REAL NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(portfolio_id, symbol)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS portfolio_vol_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    portfolio_id TEXT NOT NULL DEFAULT 'default',
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_portfolio_vol_snapshots_portfolio ON portfolio_vol_snapshots(portfolio_id, id DESC)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS portfolio_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    portfolio_id TEXT NOT NULL DEFAULT 'default',
                    alert_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    message TEXT NOT NULL,
                    acknowledged INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS subagent_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    parent_agent TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    scope_tags_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    elapsed_seconds REAL NOT NULL DEFAULT 0.0,
                    created_at TEXT NOT NULL
                )
                """
            )
            # -- Analysis artifact cache -------------------------------------------
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_artifacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    artifact_id TEXT NOT NULL UNIQUE,
                    artifact_type TEXT NOT NULL,
                    parameters_json TEXT NOT NULL DEFAULT '{}',
                    time_context_json TEXT NOT NULL DEFAULT '{}',
                    dependencies_json TEXT NOT NULL DEFAULT '[]',
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_analysis_artifacts_type "
                "ON analysis_artifacts(artifact_type, created_at DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_analysis_artifacts_expires "
                "ON analysis_artifacts(expires_at)"
            )
            # -- Three-layer memory: group tables --------------------------------
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS group_profiles (
                    group_id TEXT PRIMARY KEY,
                    group_name TEXT NOT NULL DEFAULT '',
                    group_topic TEXT NOT NULL DEFAULT '',
                    group_notes TEXT NOT NULL DEFAULT '',
                    member_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS group_members (
                    group_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    display_name TEXT NOT NULL DEFAULT '',
                    role_in_group TEXT NOT NULL DEFAULT '',
                    personality_notes TEXT NOT NULL DEFAULT '',
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (group_id, user_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS group_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL DEFAULT 'main',
                    user_id TEXT NOT NULL,
                    display_name TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_group_messages_group_thread "
                "ON group_messages(group_id, thread_id, id DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_group_members_group "
                "ON group_members(group_id, last_seen_at DESC)"
            )
            self._ensure_table_columns(
                connection,
                table_name="group_profiles",
                columns={
                    "autonomous_messages_today": "INTEGER NOT NULL DEFAULT 0",
                    "autonomous_messages_date": "TEXT NOT NULL DEFAULT ''",
                    "last_autonomous_at": "TEXT NOT NULL DEFAULT ''",
                    "bot_relational_role": "TEXT NOT NULL DEFAULT ''",
                },
            )
            self._ensure_table_columns(
                connection,
                table_name="group_members",
                columns={
                    "relational_role": "TEXT NOT NULL DEFAULT ''",
                    "username": "TEXT NOT NULL DEFAULT ''",
                },
            )
            # -- Document storage: 5-table normalized schema --------------------
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS doc_source (
                    source_id TEXT PRIMARY KEY,
                    source_code TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    source_type TEXT NOT NULL
                        CHECK (source_type IN (
                            'government_agency', 'central_bank', 'intl_org',
                            'statistics_bureau', 'news_agency'
                        )),
                    country_code TEXT NOT NULL CHECK (length(country_code) = 2),
                    default_language_code TEXT CHECK (length(default_language_code) IN (2, 5)),
                    homepage_url TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS doc_release_family (
                    release_family_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    release_code TEXT NOT NULL,
                    release_name TEXT NOT NULL,
                    topic_code TEXT NOT NULL,
                    country_code TEXT NOT NULL CHECK (length(country_code) = 2),
                    frequency TEXT,
                    default_language_code TEXT CHECK (default_language_code IS NULL OR length(default_language_code) IN (2, 5)),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (source_id) REFERENCES doc_source(source_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS document (
                    document_id TEXT PRIMARY KEY,
                    release_family_id TEXT,
                    source_id TEXT NOT NULL,
                    canonical_url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    subtitle TEXT NOT NULL DEFAULT '',
                    document_type TEXT NOT NULL
                        CHECK (document_type IN (
                            'release', 'bulletin', 'speech', 'methodology',
                            'revision_notice', 'minutes', 'statement',
                            'press_release', 'report', 'outlook'
                        )),
                    mime_type TEXT NOT NULL DEFAULT 'text/html',
                    language_code TEXT NOT NULL CHECK (length(language_code) IN (2, 5)),
                    country_code TEXT NOT NULL CHECK (length(country_code) = 2),
                    topic_code TEXT NOT NULL,
                    published_date TEXT NOT NULL,
                    published_at TEXT,
                    published_precision TEXT NOT NULL DEFAULT 'date_only',
                    published_epoch_ms INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'published'
                        CHECK (status IN ('published', 'revised', 'superseded', 'withdrawn')),
                    version_no INTEGER NOT NULL DEFAULT 1,
                    parent_document_id TEXT,
                    hash_sha256 TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    created_epoch_ms INTEGER NOT NULL DEFAULT 0,
                    updated_epoch_ms INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (release_family_id) REFERENCES doc_release_family(release_family_id),
                    FOREIGN KEY (source_id) REFERENCES doc_source(source_id),
                    FOREIGN KEY (parent_document_id) REFERENCES document(document_id)
                )
                """
            )
            self._ensure_table_columns(
                connection,
                table_name="document",
                columns={
                    "published_precision": "TEXT NOT NULL DEFAULT 'date_only'",
                    "published_epoch_ms": "INTEGER NOT NULL DEFAULT 0",
                    "created_epoch_ms": "INTEGER NOT NULL DEFAULT 0",
                    "updated_epoch_ms": "INTEGER NOT NULL DEFAULT 0",
                },
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS document_blob (
                    document_blob_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    blob_role TEXT NOT NULL
                        CHECK (blob_role IN (
                            'raw_pdf', 'raw_html', 'clean_html',
                            'plain_text', 'markdown'
                        )),
                    storage_path TEXT,
                    content_text TEXT,
                    content_bytes BLOB,
                    byte_size INTEGER,
                    encoding TEXT,
                    parser_name TEXT,
                    parser_version TEXT,
                    extracted_at TEXT,
                    FOREIGN KEY (document_id) REFERENCES document(document_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS document_extra (
                    document_id TEXT PRIMARY KEY,
                    extra_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY (document_id) REFERENCES document(document_id)
                )
                """
            )
            # -- RAG sync watermarks ----------------------------------------
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS rag_sync_watermarks (
                    source_type TEXT PRIMARY KEY,
                    last_synced_id INTEGER NOT NULL DEFAULT 0,
                    last_synced_at TEXT NOT NULL
                )
                """
            )
            # -- Document storage indexes ----------------------------------------
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_document_url "
                "ON document(canonical_url)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_document_source_date "
                "ON document(source_id, published_date)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_document_release_date "
                "ON document(release_family_id, published_date)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_document_country_topic_date "
                "ON document(country_code, topic_code, published_date)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_document_published_epoch "
                "ON document(published_epoch_ms)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_document_status "
                "ON document(status)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_blob_document_role "
                "ON document_blob(document_id, blob_role)"
            )
            # -- Observation family: 3-table hierarchy --------------------------
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS obs_source (
                    source_id TEXT PRIMARY KEY,
                    source_code TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    source_type TEXT NOT NULL
                        CHECK (source_type IN (
                            'data_aggregator', 'government_agency', 'central_bank',
                            'exchange', 'market_data'
                        )),
                    country_code TEXT NOT NULL CHECK (length(country_code) = 2),
                    homepage_url TEXT,
                    api_base_url TEXT,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS obs_family (
                    family_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    provider_series_id TEXT NOT NULL,
                    canonical_name TEXT NOT NULL,
                    short_name TEXT NOT NULL DEFAULT '',
                    unit TEXT NOT NULL DEFAULT '',
                    frequency TEXT NOT NULL DEFAULT 'irregular'
                        CHECK (frequency IN (
                            'daily','weekly','monthly','quarterly','annual','irregular'
                        )),
                    seasonal_adjustment TEXT NOT NULL DEFAULT 'none'
                        CHECK (seasonal_adjustment IN ('sa','nsa','saar','none')),
                    country_code TEXT NOT NULL CHECK (length(country_code) = 2),
                    topic_code TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT '',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    has_vintages INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (source_id) REFERENCES obs_source(source_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS obs_family_document (
                    family_id TEXT NOT NULL,
                    release_family_id TEXT NOT NULL,
                    relationship TEXT NOT NULL DEFAULT 'produced_by'
                        CHECK (relationship IN (
                            'produced_by','derived_from','related_to'
                        )),
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (family_id, release_family_id),
                    FOREIGN KEY (family_id) REFERENCES obs_family(family_id),
                    FOREIGN KEY (release_family_id) REFERENCES doc_release_family(release_family_id)
                )
                """
            )
            # ALTER TABLE migrations for obs_family_id
            try:
                connection.execute(
                    "ALTER TABLE indicators ADD COLUMN obs_family_id TEXT DEFAULT NULL"
                )
            except sqlite3.OperationalError:
                pass  # column already exists
            try:
                connection.execute(
                    "ALTER TABLE indicator_vintages ADD COLUMN obs_family_id TEXT DEFAULT NULL"
                )
            except sqlite3.OperationalError:
                pass  # column already exists
            # -- Observation family indexes --------------------------------------
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_obs_family_source "
                "ON obs_family(source_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_obs_family_country_topic "
                "ON obs_family(country_code, topic_code)"
            )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_obs_family_provider_series "
                "ON obs_family(source_id, provider_series_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_indicators_family_date "
                "ON indicators(obs_family_id, date)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_vintages_family_date "
                "ON indicator_vintages(obs_family_id, observation_date)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_obs_family_doc_release "
                "ON obs_family_document(release_family_id)"
            )

            # ── Calendar indicator normalization tables ───────────────
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS calendar_indicator (
                    indicator_id   TEXT PRIMARY KEY,
                    canonical_name TEXT NOT NULL,
                    topic          TEXT NOT NULL DEFAULT '',
                    country_code   TEXT NOT NULL,
                    frequency      TEXT NOT NULL DEFAULT 'monthly',
                    unit           TEXT NOT NULL DEFAULT '',
                    obs_family_id  TEXT DEFAULT NULL,
                    is_active      INTEGER NOT NULL DEFAULT 1,
                    created_at     TEXT NOT NULL,
                    updated_at     TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_cal_indicator_country_topic "
                "ON calendar_indicator(country_code, topic)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS calendar_indicator_alias (
                    alias_normalized TEXT NOT NULL,
                    indicator_id     TEXT NOT NULL,
                    source           TEXT NOT NULL,
                    country_code     TEXT NOT NULL,
                    alias_original   TEXT NOT NULL DEFAULT '',
                    created_at       TEXT NOT NULL,
                    PRIMARY KEY (alias_normalized, source, country_code)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_cal_alias_indicator "
                "ON calendar_indicator_alias(indicator_id)"
            )
            self._ensure_table_columns(
                connection,
                table_name="calendar_events",
                columns={"indicator_id": "TEXT DEFAULT NULL"},
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_calendar_events_indicator_id "
                "ON calendar_events(indicator_id)"
            )

    def _ensure_table_columns(
        self,
        connection: sqlite3.Connection,
        *,
        table_name: str,
        columns: dict[str, str],
    ) -> None:
        existing = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        for column_name, column_def in columns.items():
            if column_name in existing:
                continue
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}")
