"""Tests for the obs_source / obs_family / obs_family_document schema."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst.storage.sqlite import (  # noqa: E402
    DocReleaseFamilyRecord,
    DocSourceRecord,
    IndicatorObservationRecord,
    IndicatorVintageRecord,
    ObsFamilyDocumentRecord,
    ObsFamilyRecord,
    ObsSourceRecord,
    SQLiteEngineStore,
)


class TestObsFamilySchema(unittest.TestCase):
    """Verify tables are created and basic CRUD works."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "test.db"
        self.store = SQLiteEngineStore(db_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    # ── obs_source ─────────────────────────────────────────────────────

    def test_upsert_and_get_obs_source(self) -> None:
        record = ObsSourceRecord(
            source_id="fred",
            source_code="fred",
            source_name="Federal Reserve Economic Data",
            source_type="data_aggregator",
            country_code="US",
            homepage_url="https://fred.stlouisfed.org",
            api_base_url="https://api.stlouisfed.org/fred",
            is_active=True,
            created_at="2026-03-11T00:00:00Z",
            updated_at="2026-03-11T00:00:00Z",
        )
        self.store.upsert_obs_source(record)
        fetched = self.store.get_obs_source("fred")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.source_id, "fred")
        self.assertEqual(fetched.source_name, "Federal Reserve Economic Data")
        self.assertTrue(fetched.is_active)

    def test_list_obs_sources(self) -> None:
        for sid, name, active in [("fred", "FRED", True), ("eia", "EIA", False)]:
            self.store.upsert_obs_source(ObsSourceRecord(
                source_id=sid, source_code=sid, source_name=name,
                source_type="data_aggregator", country_code="US",
                homepage_url="", api_base_url="",
                is_active=active,
                created_at="2026-01-01T00:00:00Z",
                updated_at="2026-01-01T00:00:00Z",
            ))
        active = self.store.list_obs_sources(active_only=True)
        self.assertEqual(len(active), 1)
        all_sources = self.store.list_obs_sources(active_only=False)
        self.assertEqual(len(all_sources), 2)

    # ── obs_family ─────────────────────────────────────────────────────

    def test_upsert_and_get_obs_family(self) -> None:
        self._seed_obs_source("fred")
        record = ObsFamilyRecord(
            family_id="us.inflation.cpi_all",
            source_id="fred",
            provider_series_id="CPIAUCSL",
            canonical_name="CPI All Urban Consumers",
            short_name="CPI",
            unit="index",
            frequency="monthly",
            seasonal_adjustment="sa",
            country_code="US",
            topic_code="inflation",
            category="cpi_all",
            is_active=True,
            has_vintages=True,
            created_at="2026-03-11T00:00:00Z",
            updated_at="2026-03-11T00:00:00Z",
        )
        self.store.upsert_obs_family(record)
        fetched = self.store.get_obs_family("us.inflation.cpi_all")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.provider_series_id, "CPIAUCSL")
        self.assertEqual(fetched.unit, "index")
        self.assertTrue(fetched.has_vintages)

    def test_get_obs_family_by_series(self) -> None:
        self._seed_obs_source("fred")
        self._seed_obs_family("us.inflation.cpi_all", "fred", "CPIAUCSL")
        fetched = self.store.get_obs_family_by_series("fred", "CPIAUCSL")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.family_id, "us.inflation.cpi_all")

    def test_list_obs_families_with_filters(self) -> None:
        self._seed_obs_source("fred")
        self._seed_obs_family("us.inflation.cpi_all", "fred", "CPIAUCSL", topic="inflation")
        self._seed_obs_family("us.rates.fed_funds", "fred", "DFF", topic="rates", freq="daily")
        self._seed_obs_family("us.employment.unemployment", "fred", "UNRATE", topic="employment")

        # Filter by topic
        inflation = self.store.list_obs_families(topic_code="inflation")
        self.assertEqual(len(inflation), 1)

        # Filter by frequency
        daily = self.store.list_obs_families(frequency="daily")
        self.assertEqual(len(daily), 1)

        # All
        all_fams = self.store.list_obs_families()
        self.assertEqual(len(all_fams), 3)

    def test_unique_provider_series_constraint(self) -> None:
        """Same source+series_id should upsert, not duplicate."""
        self._seed_obs_source("fred")
        self._seed_obs_family("us.inflation.cpi_all", "fred", "CPIAUCSL")
        # Upsert again with different canonical name
        self.store.upsert_obs_family(ObsFamilyRecord(
            family_id="us.inflation.cpi_all",
            source_id="fred",
            provider_series_id="CPIAUCSL",
            canonical_name="Updated CPI Name",
            short_name="", unit="index", frequency="monthly",
            seasonal_adjustment="sa", country_code="US",
            topic_code="inflation", category="cpi_all",
            is_active=True, has_vintages=False,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        ))
        fetched = self.store.get_obs_family("us.inflation.cpi_all")
        self.assertEqual(fetched.canonical_name, "Updated CPI Name")

    # ── obs_family_document ────────────────────────────────────────────

    def test_upsert_and_list_obs_family_document(self) -> None:
        self._seed_obs_source("fred")
        self._seed_obs_family("us.inflation.cpi_all", "fred", "CPIAUCSL")
        self._seed_doc_source("us.bls")
        self._seed_doc_family("us.bls.cpi")

        self.store.upsert_obs_family_document(ObsFamilyDocumentRecord(
            family_id="us.inflation.cpi_all",
            release_family_id="us.bls.cpi",
            relationship="produced_by",
            created_at="2026-03-11T00:00:00Z",
        ))

        # Query from obs_family side
        releases = self.store.list_releases_for_obs_family("us.inflation.cpi_all")
        self.assertEqual(len(releases), 1)
        self.assertEqual(releases[0].release_family_id, "us.bls.cpi")

        # Query from doc_release_family side
        families = self.store.list_obs_families_for_release("us.bls.cpi")
        self.assertEqual(len(families), 1)
        self.assertEqual(families[0].family_id, "us.inflation.cpi_all")

    # ── seed function ─────────────────────────────────────────────────

    def test_seed_obs_sources_and_families(self) -> None:
        self.store.seed_obs_sources_and_families()

        sources = self.store.list_obs_sources(active_only=False)
        self.assertEqual(len(sources), 5)  # fred, eia, treasury_fiscal, nyfed, rateprobability

        families = self.store.list_obs_families(active_only=False)
        # 26 FRED + 5 EIA + 3 Treasury + 3 NY Fed = 37
        self.assertEqual(len(families), 37)

        # Spot-check a FRED family
        cpi = self.store.get_obs_family("us.inflation.cpi_all")
        self.assertIsNotNone(cpi)
        self.assertEqual(cpi.provider_series_id, "CPIAUCSL")
        self.assertEqual(cpi.unit, "index")
        self.assertEqual(cpi.seasonal_adjustment, "sa")
        self.assertTrue(cpi.has_vintages)

        # Spot-check an EIA family
        brent = self.store.get_obs_family("us.energy.brent_spot")
        self.assertIsNotNone(brent)
        self.assertEqual(brent.provider_series_id, "EIA_BRENT")
        self.assertEqual(brent.source_id, "eia")

        # Spot-check a NY Fed family
        sofr = self.store.get_obs_family("us.rates.sofr")
        self.assertIsNotNone(sofr)
        self.assertEqual(sofr.provider_series_id, "NYFED_SOFR")

    def test_seed_idempotent(self) -> None:
        """Calling seed twice should not duplicate records."""
        self.store.seed_obs_sources_and_families()
        self.store.seed_obs_sources_and_families()
        families = self.store.list_obs_families(active_only=False)
        self.assertEqual(len(families), 37)

    # ── obs_family_id on indicators ────────────────────────────────────

    def test_indicator_observation_with_obs_family_id(self) -> None:
        self._seed_obs_source("fred")
        self._seed_obs_family("us.inflation.cpi_all", "fred", "CPIAUCSL")
        self.store.upsert_indicator_observation(IndicatorObservationRecord(
            series_id="CPIAUCSL",
            source="fred",
            date="2026-03-01",
            value=315.2,
            metadata={"name": "CPI"},
            obs_family_id="us.inflation.cpi_all",
        ))
        # Verify the record is stored (no exception)
        history = self.store.get_indicator_history("CPIAUCSL", limit=1)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].value, 315.2)

    def test_indicator_observation_without_obs_family_id(self) -> None:
        """Backward compat: obs_family_id=None should still work."""
        self.store.upsert_indicator_observation(IndicatorObservationRecord(
            series_id="CUSTOM_SERIES",
            source="test",
            date="2026-03-01",
            value=42.0,
        ))
        history = self.store.get_indicator_history("CUSTOM_SERIES", limit=1)
        self.assertEqual(len(history), 1)

    def test_indicator_vintage_with_obs_family_id(self) -> None:
        self._seed_obs_source("fred")
        self._seed_obs_family("us.growth.gdp_nominal", "fred", "GDP")
        self.store.upsert_indicator_vintage(IndicatorVintageRecord(
            series_id="GDP",
            source="fred",
            observation_date="2025-10-01",
            vintage_date="2026-01-30",
            value=29000.5,
            metadata={"name": "GDP"},
            obs_family_id="us.growth.gdp_nominal",
        ))
        vintages = self.store.get_vintages_for_series("GDP", limit=1)
        self.assertEqual(len(vintages), 1)

    # ── backfill ───────────────────────────────────────────────────────

    def test_backfill_obs_family_ids(self) -> None:
        """Backfill should populate obs_family_id on existing NULL rows."""
        # Insert indicator without obs_family_id
        self.store.upsert_indicator_observation(IndicatorObservationRecord(
            series_id="CPIAUCSL", source="fred", date="2026-03-01", value=315.2,
        ))
        # Now seed families
        self.store.seed_obs_sources_and_families()
        # Backfill
        updated = self.store.backfill_obs_family_ids()
        self.assertGreater(updated, 0)

    # ── build_obs_family_lookup ────────────────────────────────────────

    def test_build_obs_family_lookup(self) -> None:
        self.store.seed_obs_sources_and_families()
        lookup = self.store.build_obs_family_lookup()
        self.assertIn(("fred", "CPIAUCSL"), lookup)
        self.assertEqual(lookup[("fred", "CPIAUCSL")], "us.inflation.cpi_all")
        self.assertIn(("eia", "EIA_BRENT"), lookup)
        self.assertIn(("nyfed", "NYFED_SOFR"), lookup)

    # ── helpers ────────────────────────────────────────────────────────

    def _seed_obs_source(self, source_id: str) -> None:
        self.store.upsert_obs_source(ObsSourceRecord(
            source_id=source_id, source_code=source_id,
            source_name=source_id.upper(),
            source_type="data_aggregator", country_code="US",
            homepage_url="", api_base_url="",
            is_active=True,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        ))

    def _seed_obs_family(
        self,
        family_id: str,
        source_id: str,
        series_id: str,
        *,
        topic: str = "inflation",
        freq: str = "monthly",
    ) -> None:
        self.store.upsert_obs_family(ObsFamilyRecord(
            family_id=family_id,
            source_id=source_id,
            provider_series_id=series_id,
            canonical_name=series_id,
            short_name="", unit="index", frequency=freq,
            seasonal_adjustment="sa", country_code="US",
            topic_code=topic, category=family_id.split(".")[-1],
            is_active=True, has_vintages=False,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        ))

    def _seed_doc_source(self, source_id: str) -> None:
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

    def _seed_doc_family(self, release_family_id: str) -> None:
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


if __name__ == "__main__":
    unittest.main()
