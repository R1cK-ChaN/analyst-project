"""SQLite mixin for analysis artifact cache CRUD."""

from __future__ import annotations

import json
from typing import Any

from analyst.analysis.artifact import Artifact, ArtifactIdentity, compute_expiry
from analyst.contracts import utc_now


class SQLiteAnalysisMixin:
    """Provides analysis artifact cache operations on ``SQLiteEngineStore``."""

    def upsert_artifact(
        self,
        identity: ArtifactIdentity,
        result: dict[str, Any],
        dependencies: list[str] | None = None,
    ) -> Artifact:
        now = utc_now()
        now_iso = now.isoformat()
        artifact_id = identity.artifact_id
        expires_at = compute_expiry(identity.artifact_type, now)
        params_json = json.dumps(identity.parameters, sort_keys=True, ensure_ascii=False)
        time_json = json.dumps(identity.time_context, sort_keys=True, ensure_ascii=False)
        deps_json = json.dumps(dependencies or [], ensure_ascii=False)
        result_json = json.dumps(result, ensure_ascii=False, default=str)

        with self._connection(commit=True) as connection:
            connection.execute(
                """
                INSERT INTO analysis_artifacts
                    (artifact_id, artifact_type, parameters_json, time_context_json,
                     dependencies_json, result_json, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(artifact_id) DO UPDATE SET
                    result_json = excluded.result_json,
                    dependencies_json = excluded.dependencies_json,
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at
                """,
                (artifact_id, identity.artifact_type, params_json, time_json,
                 deps_json, result_json, now_iso, expires_at),
            )
            row = connection.execute(
                "SELECT * FROM analysis_artifacts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
        return self._row_to_artifact(row)

    def get_artifact(self, artifact_id: str) -> Artifact | None:
        with self._connection(commit=False) as connection:
            row = connection.execute(
                "SELECT * FROM analysis_artifacts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
        return self._row_to_artifact(row) if row else None

    def get_fresh_artifact(self, artifact_id: str) -> Artifact | None:
        now_iso = utc_now().isoformat()
        with self._connection(commit=False) as connection:
            row = connection.execute(
                "SELECT * FROM analysis_artifacts WHERE artifact_id = ? AND expires_at > ?",
                (artifact_id, now_iso),
            ).fetchone()
        return self._row_to_artifact(row) if row else None

    def list_artifacts_by_type(self, artifact_type: str, *, limit: int = 10) -> list[Artifact]:
        with self._connection(commit=False) as connection:
            rows = connection.execute(
                "SELECT * FROM analysis_artifacts WHERE artifact_type = ? ORDER BY created_at DESC LIMIT ?",
                (artifact_type, limit),
            ).fetchall()
        return [self._row_to_artifact(row) for row in rows]

    def expire_stale_artifacts(self) -> int:
        now_iso = utc_now().isoformat()
        with self._connection(commit=True) as connection:
            cursor = connection.execute(
                "DELETE FROM analysis_artifacts WHERE expires_at IS NOT NULL AND expires_at < ?",
                (now_iso,),
            )
        return cursor.rowcount

    @staticmethod
    def _row_to_artifact(row: Any) -> Artifact:
        return Artifact(
            id=row["id"],
            artifact_id=row["artifact_id"],
            artifact_type=row["artifact_type"],
            parameters=json.loads(row["parameters_json"]),
            time_context=json.loads(row["time_context_json"]),
            dependencies=json.loads(row["dependencies_json"]),
            result=json.loads(row["result_json"]),
            created_at=row["created_at"],
            expires_at=row["expires_at"] or "",
        )
