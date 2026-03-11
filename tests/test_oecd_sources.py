"""Tests for OECD ingestion wiring in sources.py."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from analyst.ingestion.scrapers.oecd import OECDDataflow, OECDObservation, OECDSeries, OECDStructureSummary
from analyst.ingestion.sources import OECDIngestionClient, OECDSeriesConfig, render_oecd_series_configs


class TestOECDIngestionClient(unittest.TestCase):
    def test_refresh_builds_key_for_filter_based_series(self):
        fake_client = MagicMock()
        fake_client.get_dataflow.return_value = OECDDataflow(
            id="DSD_KEI@DF_KEI",
            agency_id="OECD.SDD.STES",
            version="4.0",
        )
        fake_client.build_key.return_value = "USA.M.UNEMP.PT_LF._T.Y._Z"
        fake_client.fetch_data.return_value = [
            OECDObservation(
                series_id="OECD_UNEMP_US",
                date="2026-01-01",
                value=4.1,
                dataflow="DSD_KEI@DF_KEI",
                dataset="DSD_KEI@DF_KEI",
                agency_id="OECD.SDD.STES",
                series_key="USA.M.UNEMP.PT_LF._T.Y._Z",
                dimensions={"REF_AREA": "USA", "TIME_PERIOD": "2026-01"},
            )
        ]

        config = OECDSeriesConfig(
            dataflow="DSD_KEI@DF_KEI",
            series_id="OECD_UNEMP_US",
            category="employment",
            filters={
                "REF_AREA": "USA",
                "FREQ": "M",
                "MEASURE": "UNEMP",
                "UNIT_MEASURE": "PT_LF",
                "ACTIVITY": "_T",
                "ADJUSTMENT": "Y",
                "TRANSFORMATION": "_Z",
            },
        )
        store = MagicMock()
        ingestion = OECDIngestionClient(fake_client, series_configs={"unemployment_us": config})

        stats = ingestion.refresh(
            store,
            family_lookup={("oecd", "OECD_UNEMP_US"): "us.employment.unemployment_oecd"},
        )

        fake_client.get_dataflow.assert_called_once_with(
            "DSD_KEI@DF_KEI",
            agency_id="OECD.SDD.STES",
            version="latest",
        )
        fake_client.build_key.assert_called_once()
        fake_client.fetch_data.assert_called_once_with(
            "DSD_KEI@DF_KEI",
            agency_id="OECD.SDD.STES",
            version="4.0",
            key="USA.M.UNEMP.PT_LF._T.Y._Z",
            series_id="OECD_UNEMP_US",
            limit=30,
        )
        store.upsert_indicator_observation.assert_called_once()
        self.assertEqual(stats.count, 1)

    def test_refresh_uses_explicit_key_without_build_key(self):
        fake_client = MagicMock()
        fake_client.get_dataflow.return_value = OECDDataflow(
            id="DSD_STES@DF_CS",
            agency_id="OECD.SDD.STES",
            version="4.0",
        )
        fake_client.fetch_data.return_value = []

        config = OECDSeriesConfig(
            dataflow="DSD_STES@DF_CS",
            series_id="OECD_CONSUMER_CONF_US",
            category="sentiment",
            key="USA.M.CCICP.*.*.*.*.*.*",
        )
        store = MagicMock()
        ingestion = OECDIngestionClient(fake_client, series_configs={"consumer_conf": config})

        stats = ingestion.refresh(store)

        fake_client.get_dataflow.assert_called_once()
        fake_client.build_key.assert_not_called()
        fake_client.fetch_data.assert_called_once_with(
            "DSD_STES@DF_CS",
            agency_id="OECD.SDD.STES",
            version="4.0",
            key="USA.M.CCICP.*.*.*.*.*.*",
            series_id="OECD_CONSUMER_CONF_US",
            limit=30,
        )
        self.assertEqual(stats.count, 0)

    def test_generate_catalog_series_configs_is_deterministic(self):
        fake_client = MagicMock()
        fake_client.list_dataflows.return_value = [
            OECDDataflow(
                id="DSD_STES@DF_CLI",
                agency_id="OECD.SDD.STES",
                version="4.1",
                name="Composite leading indicators",
            )
        ]
        fake_client.enumerate_series.return_value = [
            OECDSeries(
                key="USA.M.LI.IX._Z.NOR.IX._Z.H",
                raw_key="0:0",
                dimensions={
                    "REF_AREA": "USA",
                    "FREQ": "M",
                    "MEASURE": "LI",
                },
            )
        ]
        fake_client.series_to_filters.return_value = {
            "REF_AREA": "USA",
            "FREQ": "M",
            "MEASURE": "LI",
        }
        fake_client.build_key.return_value = "USA.M.LI"

        ingestion = OECDIngestionClient(fake_client)
        configs = ingestion.generate_catalog_series_configs(dataflow_limit=1, series_per_dataflow=1)

        self.assertEqual(len(configs), 1)
        generated = next(iter(configs.values()))
        self.assertEqual(generated.dataflow, "DSD_STES@DF_CLI")
        self.assertEqual(generated.filters["REF_AREA"], "USA")
        self.assertTrue(generated.series_id.startswith("OECD_AUTO_DSD_STES_DF_CLI_"))

    def test_refresh_catalog_stores_dynamic_series(self):
        fake_client = MagicMock()
        fake_client.list_dataflows.return_value = [
            OECDDataflow(
                id="DSD_STES@DF_CLI",
                agency_id="OECD.SDD.STES",
                version="4.1",
                name="Composite leading indicators",
                description="CLI dataset",
            )
        ]
        fake_client.fetch_data.return_value = [
            OECDObservation(
                series_id="OECD.SDD.STES:DSD_STES@DF_CLI:USA.M.LI",
                date="2026-02-01",
                value=100.7,
                dataflow="DSD_STES@DF_CLI",
                dataset="DSD_STES@DF_CLI",
                agency_id="OECD.SDD.STES",
                series_key="USA.M.LI",
                raw_series_key="0:0:0",
                dimensions={"REF_AREA": "USA", "FREQ": "M", "MEASURE": "LI", "TIME_PERIOD": "2026-02"},
            )
        ]
        store = MagicMock()
        ingestion = OECDIngestionClient(fake_client)

        stats = ingestion.refresh_catalog(store, dataflow_limit=1, sleep_seconds=0.0)

        self.assertEqual(stats.source, "oecd_catalog")
        self.assertEqual(stats.count, 1)
        fake_client.fetch_data.assert_called_once_with(
            "DSD_STES@DF_CLI",
            agency_id="OECD.SDD.STES",
            version="4.1",
            key="all",
            series_id=None,
            limit=1,
        )
        store.upsert_indicator_observation.assert_called_once()

    def test_render_oecd_series_configs_outputs_python_map(self):
        rendered = render_oecd_series_configs({
            "auto_cli": OECDSeriesConfig(
                dataflow="DSD_STES@DF_CLI",
                series_id="OECD_AUTO_DSD_STES_DF_CLI_ABCDEF123456",
                category="catalog",
                agency_id="OECD.SDD.STES",
                version="4.1",
                filters={"REF_AREA": "USA", "FREQ": "M"},
            )
        })
        self.assertIn("generated_oecd_series = {", rendered)
        self.assertIn('"auto_cli": OECDSeriesConfig(', rendered)
        self.assertIn('"REF_AREA": "USA"', rendered)


if __name__ == "__main__":
    unittest.main()
