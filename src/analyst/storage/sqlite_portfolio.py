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

class SQLitePortfolioMixin:
    def replace_portfolio_holdings(
        self,
        holdings: list[dict[str, Any]],
        portfolio_id: str = "default",
    ) -> None:
        """Replace all holdings for a portfolio (atomic swap)."""
        now = utc_now().isoformat()
        with self._connection(commit=True) as connection:
            connection.execute(
                "DELETE FROM portfolio_holdings WHERE portfolio_id = ?",
                (portfolio_id,),
            )
            for h in holdings:
                connection.execute(
                    """
                    INSERT INTO portfolio_holdings
                        (portfolio_id, symbol, name, asset_class, weight, notional, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        portfolio_id,
                        h["symbol"],
                        h["name"],
                        h["asset_class"],
                        h["weight"],
                        h["notional"],
                        now,
                    ),
                )

    def list_portfolio_holdings(
        self, portfolio_id: str = "default",
    ) -> list[dict[str, Any]]:
        """Return holdings for a portfolio as list of dicts."""
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT symbol, name, asset_class, weight, notional, updated_at
                FROM portfolio_holdings
                WHERE portfolio_id = ?
                ORDER BY weight DESC
                """,
                (portfolio_id,),
            ).fetchall()
        return [
            {
                "symbol": row["symbol"],
                "name": row["name"],
                "asset_class": row["asset_class"],
                "weight": row["weight"],
                "notional": row["notional"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def save_vol_snapshot(
        self,
        portfolio_id: str,
        snapshot_json: dict[str, Any],
    ) -> int:
        """Persist a volatility snapshot, return its id."""
        now = utc_now().isoformat()
        with self._connection(commit=True) as connection:
            cursor = connection.execute(
                """
                INSERT INTO portfolio_vol_snapshots (portfolio_id, snapshot_json, created_at)
                VALUES (?, ?, ?)
                """,
                (
                    portfolio_id,
                    json.dumps(snapshot_json, ensure_ascii=False, sort_keys=True),
                    now,
                ),
            )
            return int(cursor.lastrowid)

    def latest_vol_snapshot(
        self, portfolio_id: str = "default",
    ) -> dict[str, Any] | None:
        """Return the most recent snapshot dict, or None."""
        with self._connection(commit=False) as connection:
            row = connection.execute(
                """
                SELECT snapshot_json FROM portfolio_vol_snapshots
                WHERE portfolio_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (portfolio_id,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["snapshot_json"])

    def list_vol_snapshots(
        self, portfolio_id: str = "default", *, limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Return recent snapshots newest-first."""
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                """
                SELECT snapshot_json, created_at FROM portfolio_vol_snapshots
                WHERE portfolio_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (portfolio_id, limit),
            ).fetchall()
        return [
            {**json.loads(row["snapshot_json"]), "stored_at": row["created_at"]}
            for row in rows
        ]

    def save_portfolio_alert(
        self,
        portfolio_id: str,
        alert_type: str,
        severity: str,
        message: str,
    ) -> int:
        """Persist an alert, return its id."""
        now = utc_now().isoformat()
        with self._connection(commit=True) as connection:
            cursor = connection.execute(
                """
                INSERT INTO portfolio_alerts
                    (portfolio_id, alert_type, severity, message, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (portfolio_id, alert_type, severity, message, now),
            )
            return int(cursor.lastrowid)

    def list_portfolio_alerts(
        self,
        portfolio_id: str = "default",
        *,
        limit: int = 20,
        unacknowledged_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Return recent portfolio alerts."""
        conditions = ["portfolio_id = ?"]
        params: list[Any] = [portfolio_id]
        if unacknowledged_only:
            conditions.append("acknowledged = 0")
        where = " AND ".join(conditions)
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                f"""
                SELECT id, alert_type, severity, message, acknowledged, created_at
                FROM portfolio_alerts
                WHERE {where}
                ORDER BY id DESC
                LIMIT ?
                """,
                [*params, limit],
            ).fetchall()
        return [
            {
                "id": row["id"],
                "alert_type": row["alert_type"],
                "severity": row["severity"],
                "message": row["message"],
                "acknowledged": bool(row["acknowledged"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

