"""Unit tests for the OECD SDMX REST v2 API client."""

import unittest
from unittest.mock import MagicMock

from analyst.ingestion.scrapers.oecd import (
    OECDClient,
    OECDObservation,
    _normalize_date,
)


SAMPLE_JSON = {
    "data": {
        "dataSets": [{"series": {"0:0:0:0": {"observations": {
            "0": [99.5], "1": [99.8], "2": [100.1],
        }}}}],
        "structures": [{"dimensions": {"observation": [
            {"id": "TIME_PERIOD", "values": [
                {"id": "2024-10"}, {"id": "2024-11"}, {"id": "2024-12"},
            ]}
        ]}}],
    }
}

EMPTY_JSON = {
    "data": {
        "dataSets": [{"series": {}}],
        "structures": [{"dimensions": {"observation": [
            {"id": "TIME_PERIOD", "values": []}
        ]}}],
    }
}


class TestParseJson(unittest.TestCase):
    def test_parses_json_response(self):
        result = OECDClient._parse_json(
            SAMPLE_JSON, series_id="OECD_CLI_US", dataflow="DSD_STES@DF_CLI", limit=100,
        )
        self.assertEqual(len(result), 3)
        self.assertIsInstance(result[0], OECDObservation)
        self.assertEqual(result[0].dataflow, "DSD_STES@DF_CLI")
        self.assertTrue(all(obs.series_id == "OECD_CLI_US" for obs in result))
        # Sorted descending
        self.assertEqual(result[0].date, "2024-12-01")
        self.assertAlmostEqual(result[0].value, 100.1)
        self.assertEqual(result[1].date, "2024-11-01")
        self.assertEqual(result[2].date, "2024-10-01")

    def test_skips_null_values(self):
        data = {
            "data": {
                "dataSets": [{"series": {"0:0:0": {"observations": {
                    "0": [99.5], "1": [None], "2": [100.1],
                }}}}],
                "structures": [{"dimensions": {"observation": [
                    {"id": "TIME_PERIOD", "values": [
                        {"id": "2024-10"}, {"id": "2024-11"}, {"id": "2024-12"},
                    ]}
                ]}}],
            }
        }
        result = OECDClient._parse_json(
            data, series_id="OECD_CLI_US", dataflow="DSD_STES@DF_CLI", limit=100,
        )
        self.assertEqual(len(result), 2)
        self.assertAlmostEqual(result[0].value, 100.1)
        self.assertAlmostEqual(result[1].value, 99.5)

    def test_empty_dataset(self):
        result = OECDClient._parse_json(
            EMPTY_JSON, series_id="OECD_CLI_US", dataflow="DSD_STES@DF_CLI", limit=100,
        )
        self.assertEqual(result, [])

    def test_limits_results(self):
        result = OECDClient._parse_json(
            SAMPLE_JSON, series_id="OECD_CLI_US", dataflow="DSD_STES@DF_CLI", limit=2,
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].date, "2024-12-01")
        self.assertEqual(result[1].date, "2024-11-01")


class TestNormalizeDate(unittest.TestCase):
    def test_monthly(self):
        self.assertEqual(_normalize_date("2025-12"), "2025-12-01")
        self.assertEqual(_normalize_date("2025-01"), "2025-01-01")

    def test_quarterly(self):
        self.assertEqual(_normalize_date("2025-Q1"), "2025-01-01")
        self.assertEqual(_normalize_date("2025-Q4"), "2025-10-01")

    def test_annual(self):
        self.assertEqual(_normalize_date("2024"), "2024-01-01")


class TestGetData(unittest.TestCase):
    def test_constructs_url(self):
        client = OECDClient.__new__(OECDClient)
        client.session = MagicMock()

        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = SAMPLE_JSON
        client.session.get.return_value = resp

        client.get_data(
            "DSD_STES@DF_CLI", "4.1", "USA.M.LI.IX._Z.NOR.IX._Z.H",
            series_id="OECD_CLI_US",
        )
        args, kwargs = client.session.get.call_args
        url = args[0]
        self.assertIn("sdmx.oecd.org", url)
        self.assertIn("DSD_STES@DF_CLI", url)
        self.assertIn("USA.M.LI.IX._Z.NOR.IX._Z.H", url)


if __name__ == "__main__":
    unittest.main()
