"""Tests for the analysis artifact cache — identity, storage, and tools."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from analyst.analysis.artifact import (
    Artifact,
    ArtifactIdentity,
    DEFAULT_TTL_SECONDS,
    compute_expiry,
)
from analyst.storage import SQLiteEngineStore
from analyst.tools._artifact_cache import (
    ArtifactLookupHandler,
    ArtifactStoreHandler,
    build_artifact_lookup_tool,
    build_artifact_store_tool,
)


# ---------------------------------------------------------------------------
# ArtifactIdentity
# ---------------------------------------------------------------------------

class TestArtifactIdentity(unittest.TestCase):
    def test_deterministic_id(self):
        a = ArtifactIdentity("market_snapshot", {"symbol": "SPX"}, {"date": "2026-03-15"})
        b = ArtifactIdentity("market_snapshot", {"symbol": "SPX"}, {"date": "2026-03-15"})
        self.assertEqual(a.artifact_id, b.artifact_id)

    def test_different_params_different_id(self):
        a = ArtifactIdentity("market_snapshot", {"symbol": "SPX"}, {})
        b = ArtifactIdentity("market_snapshot", {"symbol": "NDX"}, {})
        self.assertNotEqual(a.artifact_id, b.artifact_id)

    def test_different_type_different_id(self):
        a = ArtifactIdentity("market_snapshot", {"symbol": "SPX"}, {})
        b = ArtifactIdentity("rate_analysis", {"symbol": "SPX"}, {})
        self.assertNotEqual(a.artifact_id, b.artifact_id)

    def test_different_time_context_different_id(self):
        a = ArtifactIdentity("macro_indicator", {"country": "US"}, {"date": "2026-01"})
        b = ArtifactIdentity("macro_indicator", {"country": "US"}, {"date": "2026-02"})
        self.assertNotEqual(a.artifact_id, b.artifact_id)

    def test_id_is_16_hex_chars(self):
        identity = ArtifactIdentity("market_snapshot", {"x": 1}, {})
        self.assertEqual(len(identity.artifact_id), 16)
        int(identity.artifact_id, 16)  # should not raise

    def test_param_order_independent(self):
        a = ArtifactIdentity("x", {"b": 2, "a": 1}, {})
        b = ArtifactIdentity("x", {"a": 1, "b": 2}, {})
        self.assertEqual(a.artifact_id, b.artifact_id)

    def test_empty_defaults(self):
        identity = ArtifactIdentity("test_type")
        self.assertIsInstance(identity.artifact_id, str)
        self.assertEqual(len(identity.artifact_id), 16)


class TestComputeExpiry(unittest.TestCase):
    def test_known_type_uses_ttl(self):
        now = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)
        expiry = compute_expiry("market_snapshot", now)
        expected = (now + timedelta(seconds=3600)).isoformat()
        self.assertEqual(expiry, expected)

    def test_unknown_type_uses_default(self):
        now = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)
        expiry = compute_expiry("unknown_type", now)
        expected = (now + timedelta(seconds=7200)).isoformat()
        self.assertEqual(expiry, expected)


# ---------------------------------------------------------------------------
# SQLiteAnalysisMixin
# ---------------------------------------------------------------------------

class TestSQLiteAnalysis(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = SQLiteEngineStore(db_path=Path(self._tmpdir.name) / "test.db")

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_upsert_and_get(self):
        identity = ArtifactIdentity("market_snapshot", {"symbol": "SPX"}, {"date": "2026-03-15"})
        result = {"price": 5800, "change": -0.3}
        artifact = self.store.upsert_artifact(identity, result)
        self.assertEqual(artifact.artifact_id, identity.artifact_id)
        self.assertEqual(artifact.result, result)

        retrieved = self.store.get_artifact(identity.artifact_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.result, result)

    def test_get_fresh_returns_fresh(self):
        identity = ArtifactIdentity("market_snapshot", {"symbol": "NDX"}, {})
        self.store.upsert_artifact(identity, {"price": 20000})
        fresh = self.store.get_fresh_artifact(identity.artifact_id)
        self.assertIsNotNone(fresh)

    def test_get_fresh_returns_none_when_expired(self):
        identity = ArtifactIdentity("market_snapshot", {"symbol": "DJI"}, {})
        self.store.upsert_artifact(identity, {"price": 42000})
        # Manually expire the artifact
        past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        with self.store._connection(commit=True) as conn:
            conn.execute(
                "UPDATE analysis_artifacts SET expires_at = ? WHERE artifact_id = ?",
                (past, identity.artifact_id),
            )
        fresh = self.store.get_fresh_artifact(identity.artifact_id)
        self.assertIsNone(fresh)

    def test_upsert_overwrites(self):
        identity = ArtifactIdentity("rate_analysis", {"rate": "sofr"}, {})
        self.store.upsert_artifact(identity, {"rate": 5.0})
        self.store.upsert_artifact(identity, {"rate": 5.25})
        artifact = self.store.get_artifact(identity.artifact_id)
        self.assertEqual(artifact.result["rate"], 5.25)

    def test_expire_stale(self):
        id_fresh = ArtifactIdentity("a", {"k": "fresh"}, {})
        id_stale = ArtifactIdentity("b", {"k": "stale"}, {})
        self.store.upsert_artifact(id_fresh, {"v": 1})
        self.store.upsert_artifact(id_stale, {"v": 2})
        past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        with self.store._connection(commit=True) as conn:
            conn.execute(
                "UPDATE analysis_artifacts SET expires_at = ? WHERE artifact_id = ?",
                (past, id_stale.artifact_id),
            )
        deleted = self.store.expire_stale_artifacts()
        self.assertEqual(deleted, 1)
        self.assertIsNotNone(self.store.get_artifact(id_fresh.artifact_id))
        self.assertIsNone(self.store.get_artifact(id_stale.artifact_id))

    def test_list_by_type(self):
        self.store.upsert_artifact(ArtifactIdentity("t1", {"a": 1}, {}), {"v": 1})
        self.store.upsert_artifact(ArtifactIdentity("t1", {"a": 2}, {}), {"v": 2})
        self.store.upsert_artifact(ArtifactIdentity("t2", {"a": 3}, {}), {"v": 3})
        results = self.store.list_artifacts_by_type("t1")
        self.assertEqual(len(results), 2)
        self.assertTrue(all(a.artifact_type == "t1" for a in results))

    def test_dependencies_stored(self):
        identity = ArtifactIdentity("research_analysis", {"q": "inflation"}, {})
        deps = ["abc123", "def456"]
        artifact = self.store.upsert_artifact(identity, {"summary": "up"}, deps)
        self.assertEqual(artifact.dependencies, deps)


# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------

class TestArtifactLookupHandler(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = SQLiteEngineStore(db_path=Path(self._tmpdir.name) / "test.db")

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_miss(self):
        handler = ArtifactLookupHandler(self.store)
        result = handler({"artifact_type": "market_snapshot", "parameters": {"symbol": "SPX"}})
        self.assertEqual(result["status"], "miss")

    def test_hit(self):
        identity = ArtifactIdentity("market_snapshot", {"symbol": "SPX"}, {})
        self.store.upsert_artifact(identity, {"price": 5800})
        handler = ArtifactLookupHandler(self.store)
        result = handler({"artifact_type": "market_snapshot", "parameters": {"symbol": "SPX"}})
        self.assertEqual(result["status"], "hit")
        self.assertEqual(result["result"]["price"], 5800)

    def test_empty_type_returns_error(self):
        handler = ArtifactLookupHandler(self.store)
        result = handler({"artifact_type": "", "parameters": {}})
        self.assertEqual(result["status"], "error")


class TestArtifactStoreHandler(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = SQLiteEngineStore(db_path=Path(self._tmpdir.name) / "test.db")

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_store_creates_artifact(self):
        handler = ArtifactStoreHandler(self.store)
        result = handler({
            "artifact_type": "macro_indicator",
            "parameters": {"series": "CPI"},
            "result": {"value": 3.2},
        })
        self.assertEqual(result["status"], "stored")
        self.assertIn("artifact_id", result)

    def test_store_missing_result_returns_error(self):
        handler = ArtifactStoreHandler(self.store)
        result = handler({
            "artifact_type": "macro_indicator",
            "parameters": {"series": "CPI"},
        })
        self.assertEqual(result["status"], "error")

    def test_store_non_dict_result_returns_error(self):
        handler = ArtifactStoreHandler(self.store)
        result = handler({
            "artifact_type": "macro_indicator",
            "parameters": {"series": "CPI"},
            "result": "not a dict",
        })
        self.assertEqual(result["status"], "error")


# ---------------------------------------------------------------------------
# Tool builders
# ---------------------------------------------------------------------------

class TestToolBuilders(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store = SQLiteEngineStore(db_path=Path(self._tmpdir.name) / "test.db")

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_lookup_tool_schema(self):
        tool = build_artifact_lookup_tool(self.store)
        self.assertEqual(tool.name, "check_artifact_cache")
        self.assertIn("artifact_type", tool.parameters["required"])
        self.assertIn("parameters", tool.parameters["required"])

    def test_store_tool_schema(self):
        tool = build_artifact_store_tool(self.store)
        self.assertEqual(tool.name, "store_artifact")
        self.assertIn("result", tool.parameters["required"])


if __name__ == "__main__":
    unittest.main()
