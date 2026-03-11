"""Tests for the 5-table normalized document storage schema."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from analyst.storage import (
    DocReleaseFamilyRecord,
    DocSourceRecord,
    DocumentBlobRecord,
    DocumentExtraRecord,
    DocumentRecord,
    SQLiteEngineStore,
)


class TestDocumentStorageSchema(unittest.TestCase):
    """Verify tables are created and basic CRUD works."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "test.db"
        self.store = SQLiteEngineStore(db_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    # ── doc_source ────────────────────────────────────────────────────

    def test_upsert_and_get_doc_source(self) -> None:
        record = DocSourceRecord(
            source_id="us.bls",
            source_code="bls",
            source_name="BLS",
            source_type="government_agency",
            country_code="US",
            default_language_code="en",
            homepage_url="https://www.bls.gov",
            is_active=True,
            created_at="2026-03-11T00:00:00Z",
            updated_at="2026-03-11T00:00:00Z",
        )
        self.store.upsert_doc_source(record)
        fetched = self.store.get_doc_source("us.bls")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.source_id, "us.bls")
        self.assertEqual(fetched.source_name, "BLS")
        self.assertTrue(fetched.is_active)

    def test_list_doc_sources(self) -> None:
        for sid, name, active in [("us.bls", "BLS", True), ("us.fed", "Federal Reserve", False)]:
            self.store.upsert_doc_source(DocSourceRecord(
                source_id=sid, source_code=sid.split(".")[-1],
                source_name=name, source_type="government_agency",
                country_code="US", default_language_code="en",
                homepage_url="", is_active=active,
                created_at="2026-01-01T00:00:00Z", updated_at="2026-01-01T00:00:00Z",
            ))
        active = self.store.list_doc_sources(active_only=True)
        self.assertEqual(len(active), 1)
        all_sources = self.store.list_doc_sources(active_only=False)
        self.assertEqual(len(all_sources), 2)

    # ── doc_release_family ────────────────────────────────────────────

    def test_upsert_and_get_release_family(self) -> None:
        self._seed_source("us.bls")
        record = DocReleaseFamilyRecord(
            release_family_id="us.bls.cpi",
            source_id="us.bls",
            release_code="cpi",
            release_name="Consumer Price Index",
            topic_code="inflation",
            country_code="US",
            frequency="monthly",
            default_language_code="en",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )
        self.store.upsert_doc_release_family(record)
        fetched = self.store.get_doc_release_family("us.bls.cpi")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.topic_code, "inflation")

    def test_list_release_families_by_source(self) -> None:
        self._seed_source("us.bls")
        for rfid, topic in [("us.bls.cpi", "inflation"), ("us.bls.nfp", "employment")]:
            self.store.upsert_doc_release_family(DocReleaseFamilyRecord(
                release_family_id=rfid, source_id="us.bls",
                release_code=rfid.split(".")[-1], release_name=rfid,
                topic_code=topic, country_code="US", frequency="monthly",
                default_language_code="en",
                created_at="2026-01-01T00:00:00Z", updated_at="2026-01-01T00:00:00Z",
            ))
        families = self.store.list_doc_release_families(source_id="us.bls")
        self.assertEqual(len(families), 2)

    # ── document ──────────────────────────────────────────────────────

    def test_upsert_and_get_document(self) -> None:
        self._seed_source("us.bls")
        self._seed_family("us.bls.cpi")
        doc = self._make_document("doc001", "https://bls.gov/cpi/2026")
        self.store.upsert_document(doc)
        fetched = self.store.get_document("doc001")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.title, "CPI March 2026")
        expected_published_ms = int(datetime(2026, 3, 11, tzinfo=timezone.utc).timestamp() * 1000)
        self.assertEqual(fetched.published_epoch_ms, expected_published_ms)
        self.assertGreater(fetched.created_epoch_ms, 0)
        self.assertGreater(fetched.updated_epoch_ms, 0)

    def test_document_exists(self) -> None:
        self._seed_source("us.bls")
        self._seed_family("us.bls.cpi")
        self.assertFalse(self.store.document_exists("https://bls.gov/cpi/2026"))
        self.store.upsert_document(self._make_document("d01", "https://bls.gov/cpi/2026"))
        self.assertTrue(self.store.document_exists("https://bls.gov/cpi/2026"))

    def test_get_document_by_url(self) -> None:
        self._seed_source("us.bls")
        self._seed_family("us.bls.cpi")
        self.store.upsert_document(self._make_document("d02", "https://bls.gov/cpi/2026-02"))
        fetched = self.store.get_document_by_url("https://bls.gov/cpi/2026-02")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.document_id, "d02")

    def test_list_documents_with_filters(self) -> None:
        self._seed_source("us.bls")
        self._seed_family("us.bls.cpi")
        for i in range(3):
            self.store.upsert_document(self._make_document(
                f"d{i}", f"https://bls.gov/cpi/{i}",
                published_date=f"2026-03-{10+i:02d}",
            ))
        docs = self.store.list_documents(source_id="us.bls", limit=2)
        self.assertEqual(len(docs), 2)
        # Most recent first
        self.assertEqual(docs[0].published_date, "2026-03-12")

        docs_by_topic = self.store.list_documents(topic_code="inflation")
        self.assertEqual(len(docs_by_topic), 3)

    def test_unique_canonical_url(self) -> None:
        self._seed_source("us.bls")
        self._seed_family("us.bls.cpi")
        url = "https://bls.gov/cpi/unique"
        self.store.upsert_document(self._make_document("d1", url, title="V1"))
        self.store.upsert_document(self._make_document("d1", url, title="V2"))
        fetched = self.store.get_document("d1")
        self.assertEqual(fetched.title, "V2")

    # ── document_blob ─────────────────────────────────────────────────

    def test_upsert_and_get_blob(self) -> None:
        self._seed_source("us.bls")
        self._seed_family("us.bls.cpi")
        self.store.upsert_document(self._make_document("d1", "https://bls.gov/cpi/1"))
        blob = DocumentBlobRecord(
            document_blob_id="d1_md",
            document_id="d1",
            blob_role="markdown",
            storage_path="",
            content_text="# CPI Report\n\nInflation rose 0.3%.",
            content_bytes=None,
            byte_size=36,
            encoding="utf-8",
            parser_name="markdownify",
            parser_version="0.12",
            extracted_at="2026-03-11T00:00:00Z",
        )
        self.store.upsert_document_blob(blob)
        fetched = self.store.get_document_blob("d1", "markdown")
        self.assertIsNotNone(fetched)
        self.assertIn("CPI Report", fetched.content_text)

    def test_list_document_blobs(self) -> None:
        self._seed_source("us.bls")
        self._seed_family("us.bls.cpi")
        self.store.upsert_document(self._make_document("d1", "https://bls.gov/cpi/1"))
        for role in ("markdown", "raw_html"):
            self.store.upsert_document_blob(DocumentBlobRecord(
                document_blob_id=f"d1_{role}",
                document_id="d1", blob_role=role,
                storage_path="", content_text="content",
                content_bytes=None, byte_size=7, encoding="utf-8",
                parser_name="", parser_version="",
                extracted_at="2026-03-11T00:00:00Z",
            ))
        blobs = self.store.list_document_blobs("d1")
        self.assertEqual(len(blobs), 2)

    # ── document_extra ────────────────────────────────────────────────

    def test_upsert_and_get_extra(self) -> None:
        self._seed_source("us.bls")
        self._seed_family("us.bls.cpi")
        self.store.upsert_document(self._make_document("d1", "https://bls.gov/cpi/1"))
        extra = DocumentExtraRecord(
            document_id="d1",
            extra_json={"importance": "high", "institution": "BLS"},
        )
        self.store.upsert_document_extra(extra)
        fetched = self.store.get_document_extra("d1")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.extra_json["importance"], "high")

    # ── seed_doc_sources_and_families ─────────────────────────────────

    def test_seed_from_gov_configs(self) -> None:
        sample_configs = {
            "us": {
                "us_bls_cpi": {
                    "institution": "BLS",
                    "country": "US",
                    "language": "en",
                    "data_category": "inflation",
                    "url": "https://www.bls.gov/cpi",
                },
                "us_bls_nfp": {
                    "institution": "BLS",
                    "country": "US",
                    "language": "en",
                    "data_category": "employment",
                    "url": "https://www.bls.gov/nfp",
                },
            },
            "cn": {
                "cn_nbs_gdp": {
                    "institution": "国家统计局",
                    "country": "CN",
                    "language": "zh",
                    "data_category": "gdp",
                    "url": "https://www.stats.gov.cn",
                },
            },
        }
        self.store.seed_doc_sources_and_families(sample_configs)
        sources = self.store.list_doc_sources(active_only=False)
        # us.bls + cn.nbs = 2 sources
        self.assertEqual(len(sources), 2)
        families = self.store.list_doc_release_families()
        # cpi + nfp + gdp = 3 families
        self.assertEqual(len(families), 3)

        # Check source types
        bls = self.store.get_doc_source("us.bls")
        self.assertEqual(bls.source_type, "government_agency")
        nbs = self.store.get_doc_source("cn.nbs")
        self.assertEqual(nbs.source_type, "statistics_bureau")

    # ── helpers ───────────────────────────────────────────────────────

    def _seed_source(self, source_id: str) -> None:
        self.store.upsert_doc_source(DocSourceRecord(
            source_id=source_id,
            source_code=source_id.split(".")[-1],
            source_name=source_id.upper(),
            source_type="government_agency",
            country_code=source_id.split(".")[0].upper(),
            default_language_code="en",
            homepage_url="",
            is_active=True,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        ))

    def _seed_family(self, release_family_id: str) -> None:
        parts = release_family_id.split(".")
        self.store.upsert_doc_release_family(DocReleaseFamilyRecord(
            release_family_id=release_family_id,
            source_id=f"{parts[0]}.{parts[1]}",
            release_code=parts[-1],
            release_name=parts[-1].upper(),
            topic_code="inflation",
            country_code=parts[0].upper(),
            frequency="monthly",
            default_language_code="en",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        ))

    def _make_document(
        self,
        doc_id: str,
        url: str,
        *,
        title: str = "CPI March 2026",
        published_date: str = "2026-03-11",
    ) -> DocumentRecord:
        return DocumentRecord(
            document_id=doc_id,
            release_family_id="us.bls.cpi",
            source_id="us.bls",
            canonical_url=url,
            title=title,
            subtitle="",
            document_type="release",
            mime_type="text/html",
            language_code="en",
            country_code="US",
            topic_code="inflation",
            published_date=published_date,
            published_at="2026-03-11T00:00:00Z",
            status="published",
            version_no=1,
            parent_document_id="",
            hash_sha256="abc123",
            created_at="2026-03-11T00:00:00Z",
            updated_at="2026-03-11T00:00:00Z",
        )


if __name__ == "__main__":
    unittest.main()
