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

class SQLiteResearchMixin:
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
                    json.dumps(regime_json, ensure_ascii=False, sort_keys=True),
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
                    json.dumps(regime_json, ensure_ascii=False, sort_keys=True) if regime_json else None,
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
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

    def list_recent_regime_snapshots(self, *, limit: int = 3) -> list[RegimeSnapshotRecord]:
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT * FROM regime_snapshots
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            RegimeSnapshotRecord(
                snapshot_id=int(row["id"]),
                timestamp=row["timestamp"],
                regime_json=json.loads(row["regime_json"]),
                trigger_event=row["trigger_event"],
                summary=row["summary"],
            )
            for row in rows
        ]

    def list_recent_generated_notes(
        self,
        *,
        limit: int = 5,
        note_type: str | None = None,
    ) -> list[GeneratedNoteRecord]:
        conditions: list[str] = []
        params: list[Any] = []
        if note_type:
            conditions.append("note_type = ?")
            params.append(note_type)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT * FROM generated_notes
                {where_clause}
                ORDER BY id DESC
                LIMIT ?
                """.format(where_clause=where_clause),
                [*params, limit],
            ).fetchall()
        return [
            GeneratedNoteRecord(
                note_id=int(row["id"]),
                created_at=row["created_at"],
                note_type=row["note_type"],
                title=row["title"],
                summary=row["summary"],
                body_markdown=row["body_markdown"],
                regime_json=json.loads(row["regime_json"]) if row["regime_json"] else None,
                metadata=json.loads(row["metadata_json"]),
            )
            for row in rows
        ]

    def add_analytical_observation(
        self,
        *,
        observation_type: str,
        summary: str,
        detail: str,
        source_kind: str,
        source_id: int,
        metadata: dict[str, Any] | None = None,
    ) -> AnalyticalObservationRecord:
        created_at = utc_now().isoformat()
        with self._connection(commit=True) as connection:
            cursor = connection.execute(
                """
                INSERT INTO analytical_observations (
                    observation_type,
                    summary,
                    detail,
                    source_kind,
                    source_id,
                    metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation_type,
                    summary,
                    detail,
                    source_kind,
                    source_id,
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                    created_at,
                ),
            )
            observation_id = int(cursor.lastrowid)
        return AnalyticalObservationRecord(
            observation_id=observation_id,
            observation_type=observation_type,
            summary=summary,
            detail=detail,
            source_kind=source_kind,
            source_id=source_id,
            created_at=created_at,
            metadata=metadata or {},
        )

    def list_recent_analytical_observations(self, *, limit: int = 5) -> list[AnalyticalObservationRecord]:
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT * FROM analytical_observations
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            AnalyticalObservationRecord(
                observation_id=int(row["id"]),
                observation_type=row["observation_type"],
                summary=row["summary"],
                detail=row["detail"],
                source_kind=row["source_kind"],
                source_id=int(row["source_id"]),
                created_at=row["created_at"],
                metadata=json.loads(row["metadata_json"]),
            )
            for row in rows
        ]

    def list_tagged_observations(self, *, tags: list[str], limit: int = 4) -> list[AnalyticalObservationRecord]:
        if not tags:
            return self.list_recent_analytical_observations(limit=limit)
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT * FROM analytical_observations
                ORDER BY id DESC
                """,
            ).fetchall()
        matched: list[AnalyticalObservationRecord] = []
        for row in rows:
            if not _matches_scope_tags(row["summary"], tags):
                continue
            matched.append(
                AnalyticalObservationRecord(
                    observation_id=int(row["id"]),
                    observation_type=row["observation_type"],
                    summary=row["summary"],
                    detail=row["detail"],
                    source_kind=row["source_kind"],
                    source_id=int(row["source_id"]),
                    created_at=row["created_at"],
                    metadata=json.loads(row["metadata_json"]),
                )
            )
            if len(matched) >= limit:
                break
        return matched

    def list_tagged_regime_snapshots(self, *, tags: list[str], limit: int = 2) -> list[RegimeSnapshotRecord]:
        if not tags:
            return self.list_recent_regime_snapshots(limit=limit)
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT * FROM regime_snapshots
                ORDER BY id DESC
                """,
            ).fetchall()
        matched: list[RegimeSnapshotRecord] = []
        for row in rows:
            if not _matches_scope_tags(row["summary"], tags):
                continue
            matched.append(
                RegimeSnapshotRecord(
                    snapshot_id=int(row["id"]),
                    timestamp=row["timestamp"],
                    regime_json=json.loads(row["regime_json"]),
                    trigger_event=row["trigger_event"],
                    summary=row["summary"],
                )
            )
            if len(matched) >= limit:
                break
        return matched

    def save_subagent_run(
        self,
        *,
        task_id: str,
        parent_agent: str,
        task_type: str,
        objective: str,
        scope_tags: list[str],
        status: str,
        summary: str,
        elapsed_seconds: float,
    ) -> None:
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                INSERT INTO subagent_runs (
                    task_id, parent_agent, task_type, objective,
                    scope_tags_json, status, summary, elapsed_seconds, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    parent_agent,
                    task_type,
                    objective,
                    json.dumps(scope_tags, ensure_ascii=False),
                    status,
                    summary,
                    elapsed_seconds,
                    utc_now().isoformat(),
                ),
            )

    def list_recent_subagent_runs(
        self,
        *,
        parent_agent: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        with self._connection(commit=False) as connection:
            if parent_agent:
                rows = connection.execute(
                    "SELECT * FROM subagent_runs WHERE parent_agent = ? ORDER BY id DESC LIMIT ?",
                    (parent_agent, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM subagent_runs ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [
            {
                "id": row["id"],
                "task_id": row["task_id"],
                "parent_agent": row["parent_agent"],
                "task_type": row["task_type"],
                "objective": row["objective"],
                "scope_tags": json.loads(row["scope_tags_json"]),
                "status": row["status"],
                "summary": row["summary"],
                "elapsed_seconds": row["elapsed_seconds"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def publish_research_artifact(
        self,
        *,
        artifact_type: str,
        title: str,
        summary: str,
        content_markdown: str,
        source_kind: str,
        source_id: int,
        tags: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> ResearchArtifactRecord:
        created_at = utc_now().isoformat()
        with self._connection(commit=True) as connection:
            cursor = connection.execute(
                """
                INSERT INTO research_artifacts (
                    artifact_type,
                    title,
                    summary,
                    content_markdown,
                    source_kind,
                    source_id,
                    tags_json,
                    metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_type,
                    title,
                    summary,
                    content_markdown,
                    source_kind,
                    source_id,
                    json.dumps(tags, ensure_ascii=False, sort_keys=True),
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                    created_at,
                ),
            )
            artifact_id = int(cursor.lastrowid)
        return ResearchArtifactRecord(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            title=title,
            summary=summary,
            content_markdown=content_markdown,
            source_kind=source_kind,
            source_id=source_id,
            created_at=created_at,
            tags=tags,
            metadata=metadata or {},
        )

    def list_recent_research_artifacts(
        self,
        *,
        limit: int = 5,
        artifact_types: tuple[str, ...] = (),
    ) -> list[ResearchArtifactRecord]:
        conditions: list[str] = []
        params: list[Any] = []
        if artifact_types:
            conditions.append("artifact_type IN (" + ",".join("?" for _ in artifact_types) + ")")
            params.extend(artifact_types)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT * FROM research_artifacts
                {where_clause}
                ORDER BY id DESC
                LIMIT ?
                """.format(where_clause=where_clause),
                [*params, limit],
            ).fetchall()
        return [
            ResearchArtifactRecord(
                artifact_id=int(row["id"]),
                artifact_type=row["artifact_type"],
                title=row["title"],
                summary=row["summary"],
                content_markdown=row["content_markdown"],
                source_kind=row["source_kind"],
                source_id=int(row["source_id"]),
                created_at=row["created_at"],
                tags=json.loads(row["tags_json"]),
                metadata=json.loads(row["metadata_json"]),
            )
            for row in rows
        ]

    def search_research_artifacts(
        self,
        *,
        query: str,
        limit: int = 5,
        artifact_types: tuple[str, ...] = (),
    ) -> list[ResearchArtifactRecord]:
        terms = self._search_terms(query)
        candidates = self.list_recent_research_artifacts(limit=max(limit * 20, 100), artifact_types=artifact_types)
        scored: list[tuple[float, ResearchArtifactRecord]] = []
        for artifact in candidates:
            haystack = " ".join([artifact.title, artifact.summary, artifact.content_markdown])
            score = self._score_text_match(haystack, terms)
            if score <= 0:
                continue
            scored.append((score, artifact))
        scored.sort(key=lambda item: (item[0], item[1].created_at), reverse=True)
        return [record for _, record in scored[:limit]]

    def save_trade_signal(
        self,
        *,
        signal_type: str,
        title: str,
        summary: str,
        rationale_markdown: str,
        signal: dict[str, Any],
        confidence: float,
        metadata: dict[str, Any] | None = None,
    ) -> TradeSignalRecord:
        created_at = utc_now().isoformat()
        with self._connection(commit=True) as connection:
            cursor = connection.execute(
                """
                INSERT INTO trade_signals (
                    signal_type,
                    title,
                    summary,
                    rationale_markdown,
                    signal_json,
                    confidence,
                    metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal_type,
                    title,
                    summary,
                    rationale_markdown,
                    json.dumps(signal, ensure_ascii=False, sort_keys=True),
                    confidence,
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                    created_at,
                ),
            )
            signal_id = int(cursor.lastrowid)
        return TradeSignalRecord(
            signal_id=signal_id,
            signal_type=signal_type,
            title=title,
            summary=summary,
            rationale_markdown=rationale_markdown,
            signal=signal,
            confidence=confidence,
            created_at=created_at,
            metadata=metadata or {},
        )

    def log_trading_decision(
        self,
        *,
        decision_type: str,
        title: str,
        summary: str,
        rationale_markdown: str,
        research_artifact_id: int | None,
        signal_id: int | None,
        metadata: dict[str, Any] | None = None,
    ) -> DecisionLogRecord:
        created_at = utc_now().isoformat()
        with self._connection(commit=True) as connection:
            cursor = connection.execute(
                """
                INSERT INTO decision_log (
                    decision_type,
                    title,
                    summary,
                    rationale_markdown,
                    research_artifact_id,
                    signal_id,
                    metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_type,
                    title,
                    summary,
                    rationale_markdown,
                    research_artifact_id,
                    signal_id,
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                    created_at,
                ),
            )
            decision_id = int(cursor.lastrowid)
        return DecisionLogRecord(
            decision_id=decision_id,
            decision_type=decision_type,
            title=title,
            summary=summary,
            rationale_markdown=rationale_markdown,
            research_artifact_id=research_artifact_id,
            signal_id=signal_id,
            created_at=created_at,
            metadata=metadata or {},
        )

    def list_recent_decisions(self, *, limit: int = 5) -> list[DecisionLogRecord]:
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT * FROM decision_log
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            DecisionLogRecord(
                decision_id=int(row["id"]),
                decision_type=row["decision_type"],
                title=row["title"],
                summary=row["summary"],
                rationale_markdown=row["rationale_markdown"],
                research_artifact_id=int(row["research_artifact_id"]) if row["research_artifact_id"] is not None else None,
                signal_id=int(row["signal_id"]) if row["signal_id"] is not None else None,
                created_at=row["created_at"],
                metadata=json.loads(row["metadata_json"]),
            )
            for row in rows
        ]

    def upsert_position_state(
        self,
        *,
        symbol: str,
        exposure: float,
        direction: str,
        thesis: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._connection(commit=True) as connection:
            connection.execute(
                """
                INSERT INTO position_state (
                    symbol,
                    exposure,
                    direction,
                    thesis,
                    metadata_json,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    exposure = excluded.exposure,
                    direction = excluded.direction,
                    thesis = excluded.thesis,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    symbol,
                    exposure,
                    direction,
                    thesis,
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                    utc_now().isoformat(),
                ),
            )

    def list_position_state(self, *, limit: int = 10) -> list[PositionStateRecord]:
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT * FROM position_state
                ORDER BY updated_at DESC, symbol ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            PositionStateRecord(
                symbol=row["symbol"],
                exposure=float(row["exposure"]),
                direction=row["direction"],
                thesis=row["thesis"],
                updated_at=row["updated_at"],
                metadata=json.loads(row["metadata_json"]),
            )
            for row in rows
        ]

    def record_performance(
        self,
        *,
        metric_name: str,
        metric_value: float,
        period_label: str,
        metadata: dict[str, Any] | None = None,
    ) -> PerformanceRecord:
        created_at = utc_now().isoformat()
        with self._connection(commit=True) as connection:
            cursor = connection.execute(
                """
                INSERT INTO performance_records (
                    metric_name,
                    metric_value,
                    period_label,
                    metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    metric_name,
                    metric_value,
                    period_label,
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                    created_at,
                ),
            )
            record_id = int(cursor.lastrowid)
        return PerformanceRecord(
            record_id=record_id,
            metric_name=metric_name,
            metric_value=metric_value,
            period_label=period_label,
            created_at=created_at,
            metadata=metadata or {},
        )

    def list_recent_performance_records(self, *, limit: int = 5) -> list[PerformanceRecord]:
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT * FROM performance_records
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            PerformanceRecord(
                record_id=int(row["id"]),
                metric_name=row["metric_name"],
                metric_value=float(row["metric_value"]),
                period_label=row["period_label"],
                created_at=row["created_at"],
                metadata=json.loads(row["metadata_json"]),
            )
            for row in rows
        ]

    def publish_trading_artifact(
        self,
        *,
        artifact_type: str,
        title: str,
        summary: str,
        rationale_markdown: str,
        research_artifact_id: int,
        signal: dict[str, Any],
        confidence: float,
        decision_log_id: int | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TradingArtifactRecord:
        created_at = utc_now().isoformat()
        with self._connection(commit=True) as connection:
            cursor = connection.execute(
                """
                INSERT INTO trading_artifacts (
                    artifact_type,
                    title,
                    summary,
                    rationale_markdown,
                    research_artifact_id,
                    decision_log_id,
                    signal_json,
                    confidence,
                    tags_json,
                    metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_type,
                    title,
                    summary,
                    rationale_markdown,
                    research_artifact_id,
                    decision_log_id,
                    json.dumps(signal, ensure_ascii=False, sort_keys=True),
                    confidence,
                    json.dumps(tags or [], ensure_ascii=False, sort_keys=True),
                    json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True),
                    created_at,
                ),
            )
            artifact_id = int(cursor.lastrowid)
        return TradingArtifactRecord(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            title=title,
            summary=summary,
            rationale_markdown=rationale_markdown,
            research_artifact_id=research_artifact_id,
            decision_log_id=decision_log_id,
            signal=signal,
            confidence=confidence,
            created_at=created_at,
            tags=tags or [],
            metadata=metadata or {},
        )

    def list_recent_trading_artifacts(self, *, limit: int = 5) -> list[TradingArtifactRecord]:
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT * FROM trading_artifacts
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            TradingArtifactRecord(
                artifact_id=int(row["id"]),
                artifact_type=row["artifact_type"],
                title=row["title"],
                summary=row["summary"],
                rationale_markdown=row["rationale_markdown"],
                research_artifact_id=int(row["research_artifact_id"]),
                decision_log_id=int(row["decision_log_id"]) if row["decision_log_id"] is not None else None,
                signal=json.loads(row["signal_json"]),
                confidence=float(row["confidence"]),
                created_at=row["created_at"],
                tags=json.loads(row["tags_json"]),
                metadata=json.loads(row["metadata_json"]),
            )
            for row in rows
        ]

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

