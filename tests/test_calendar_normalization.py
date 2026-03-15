"""Tests for calendar event indicator normalization."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from analyst.utils import normalize_indicator_name
from analyst.storage.sqlite import (
    CalendarIndicatorRecord,
    CalendarIndicatorAliasRecord,
    SQLiteEngineStore,
    StoredEventRecord,
    _CALENDAR_ALIAS_DEFS,
    _CALENDAR_INDICATOR_DEFS,
)


class TestNormalizeIndicatorName(unittest.TestCase):
    def test_basic_lowering_and_strip(self):
        self.assertEqual(normalize_indicator_name("  CPI MoM  "), "cpi mom")

    def test_collapse_whitespace(self):
        self.assertEqual(normalize_indicator_name("CPI   m/m"), "cpi m/m")

    def test_strip_month_suffix(self):
        self.assertEqual(normalize_indicator_name("Inflation Rate YoY (Mar)"), "inflation rate yoy")
        self.assertEqual(normalize_indicator_name("CPI MoM (January)"), "cpi mom")

    def test_no_strip_non_month(self):
        self.assertEqual(normalize_indicator_name("ISM PMI (Final)"), "ism pmi (final)")

    def test_empty_string(self):
        self.assertEqual(normalize_indicator_name(""), "")


class TestCalendarIndicatorCRUD(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / ".analyst" / "engine.db"
        self.store = SQLiteEngineStore(db_path=self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_seed_calendar_indicators(self):
        self.store.seed_calendar_indicators()
        indicators = self.store.list_calendar_indicators(active_only=False)
        self.assertEqual(len(indicators), len(_CALENDAR_INDICATOR_DEFS))
        # Spot-check one
        cpi = self.store.get_calendar_indicator("us.inflation.cpi_mom")
        self.assertIsNotNone(cpi)
        self.assertEqual(cpi.canonical_name, "CPI MoM")
        self.assertEqual(cpi.country_code, "US")
        self.assertEqual(cpi.topic, "inflation")

    def test_seed_populates_aliases(self):
        self.store.seed_calendar_indicators()
        aliases = self.store.list_aliases_for_indicator("us.inflation.cpi_mom")
        self.assertGreater(len(aliases), 0)
        sources = {a.source for a in aliases}
        self.assertIn("investing", sources)

    def test_resolve_alias_exact(self):
        self.store.seed_calendar_indicators()
        # Investing.com variant
        result = self.store.resolve_calendar_alias("CPI m/m", "investing", "US")
        self.assertEqual(result, "us.inflation.cpi_mom")
        # TradingEconomics variant
        result = self.store.resolve_calendar_alias("Inflation Rate MoM", "tradingeconomics", "US")
        self.assertEqual(result, "us.inflation.cpi_mom")
        # ForexFactory NFP
        result = self.store.resolve_calendar_alias("Non-Farm Payrolls", "forexfactory", "US")
        self.assertEqual(result, "us.employment.nfp")

    def test_resolve_alias_with_month_suffix(self):
        self.store.seed_calendar_indicators()
        result = self.store.resolve_calendar_alias("Inflation Rate MoM (Mar)", "tradingeconomics", "US")
        self.assertEqual(result, "us.inflation.cpi_mom")

    def test_resolve_alias_not_found(self):
        self.store.seed_calendar_indicators()
        result = self.store.resolve_calendar_alias("Totally Unknown Event", "investing", "US")
        self.assertIsNone(result)

    def test_resolve_alias_wrong_source(self):
        self.store.seed_calendar_indicators()
        # "Consumer Price Index m/m" is forexfactory-only
        result = self.store.resolve_calendar_alias("Consumer Price Index m/m", "investing", "US")
        self.assertIsNone(result)

    def test_upsert_event_with_indicator_id(self):
        event = StoredEventRecord(
            source="investing",
            event_id="test123",
            timestamp=1700000000,
            country="US",
            indicator="CPI m/m",
            category="inflation",
            importance="high",
            actual="0.3%",
            forecast="0.2%",
            previous="0.1%",
            indicator_id="us.inflation.cpi_mom",
        )
        self.store.upsert_calendar_event(event)
        # Round-trip
        results = self.store.list_indicator_releases_by_id("us.inflation.cpi_mom")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].indicator_id, "us.inflation.cpi_mom")
        self.assertEqual(results[0].actual, "0.3%")

    def test_backfill_calendar_indicator_ids(self):
        self.store.seed_calendar_indicators()
        # Insert events without indicator_id
        for source, indicator_name in [
            ("investing", "CPI m/m"),
            ("tradingeconomics", "Inflation Rate MoM"),
            ("forexfactory", "Non-Farm Payrolls"),
        ]:
            self.store.upsert_calendar_event(StoredEventRecord(
                source=source,
                event_id=f"backfill_{source}",
                timestamp=1700000000,
                country="US",
                indicator=indicator_name,
                category="inflation",
                importance="high",
                actual="0.3%",
            ))
        # Verify they have no indicator_id
        events = self.store.list_indicator_releases_by_id("us.inflation.cpi_mom")
        self.assertEqual(len(events), 0)
        # Run backfill
        updated = self.store.backfill_calendar_indicator_ids()
        self.assertGreaterEqual(updated, 2)  # at least the 2 CPI events
        # Now they should resolve
        events = self.store.list_indicator_releases_by_id("us.inflation.cpi_mom")
        self.assertGreaterEqual(len(events), 2)

    def test_list_indicator_releases_by_id_cross_source(self):
        """Cross-source query returns events from all 3 sources."""
        self.store.seed_calendar_indicators()
        base_ts = 1700000000
        for i, (source, ind_name) in enumerate([
            ("investing", "CPI m/m"),
            ("forexfactory", "Consumer Price Index m/m"),
            ("tradingeconomics", "Inflation Rate MoM"),
        ]):
            self.store.upsert_calendar_event(StoredEventRecord(
                source=source,
                event_id=f"cross_{source}_{i}",
                timestamp=base_ts + i * 86400,
                country="US",
                indicator=ind_name,
                category="inflation",
                importance="high",
                actual=f"0.{i}%",
                indicator_id="us.inflation.cpi_mom",
            ))
        results = self.store.list_indicator_releases_by_id("us.inflation.cpi_mom")
        self.assertEqual(len(results), 3)
        sources = {r.source for r in results}
        self.assertEqual(sources, {"investing", "forexfactory", "tradingeconomics"})

    def test_list_calendar_indicators_filtered(self):
        self.store.seed_calendar_indicators()
        us_inflation = self.store.list_calendar_indicators(country_code="US", topic="inflation")
        self.assertGreater(len(us_inflation), 5)
        for ind in us_inflation:
            self.assertEqual(ind.country_code, "US")
            self.assertEqual(ind.topic, "inflation")

    def test_indicator_obs_family_link(self):
        self.store.seed_calendar_indicators()
        ind = self.store.get_calendar_indicator("us.inflation.cpi_yoy")
        self.assertIsNotNone(ind)
        self.assertEqual(ind.obs_family_id, "us.inflation.cpi_all")


if __name__ == "__main__":
    unittest.main()
