"""Convenience wrapper around SQLiteEngineStore artifact methods."""

from __future__ import annotations

from typing import Any

from .artifact import Artifact, ArtifactIdentity


class ArtifactStore:
    """Thin facade that delegates to the SQLiteAnalysisMixin on a store."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def get_fresh(self, identity: ArtifactIdentity) -> Artifact | None:
        return self._store.get_fresh_artifact(identity.artifact_id)

    def upsert(
        self,
        identity: ArtifactIdentity,
        result: dict[str, Any],
        dependencies: list[str] | None = None,
    ) -> Artifact:
        return self._store.upsert_artifact(identity, result, dependencies)

    def expire_stale(self) -> int:
        return self._store.expire_stale_artifacts()
