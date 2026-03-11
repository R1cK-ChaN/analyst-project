"""Unit tests for the ECB SDMX JSON API client."""

import unittest
from unittest.mock import MagicMock

from analyst.ingestion.scrapers.ecb import (
    ECBClient,
    ECBObservation,
    _normalize_date,
)


SAMPLE_JSON = {
    "dataSets": [{"series": {"0:0:0:0:0": {"observations": {
        "0": [16500000.0, 0, 0, None, None], "1": [16600000.0, 0, 0, None, None], "2": [16700000.0, 0, 0, None, None],
    }}}}],
    "structure": {"dimensions": {"observation": [
        {"id": "TIME_PERIOD", "values": [
            {"id": "2024-10", "name": "2024-10"}, {"id": "2024-11", "name": "2024-11"}, {"id": "2024-12", "name": "2024-12"},
        ]}
    ]}}
}

EMPTY_JSON = {
    "dataSets": [{"series": {}}],
    "structure": {"dimensions": {"observation": [
        {"id": "TIME_PERIOD", "values": []}
    ]}}
}


class TestParseJson(unittest.TestCase):
    def test_parses_json_response(self):
        result = ECBClient._parse_json(
            SAMPLE_JSON, series_id="ECB_EA_M1", dataflow="BSI", limit=100,
        )
        self.assertEqual(len(result), 3)
        self.assertIsInstance(result[0], ECBObservation)
        self.assertEqual(result[0].dataflow, "BSI")
        self.assertTrue(all(obs.series_id == "ECB_EA_M1" for obs in result))
        # Sorted descending
        self.assertEqual(result[0].date, "2024-12-01")
        self.assertAlmostEqual(result[0].value, 16700000.0)
        self.assertEqual(result[1].date, "2024-11-01")
        self.assertEqual(result[2].date, "2024-10-01")

    def test_skips_null_values(self):
        data = {
            "dataSets": [{"series": {"0:0:0": {"observations": {
                "0": [16500000.0], "1": [None], "2": [16700000.0],
            }}}}],
            "structure": {"dimensions": {"observation": [
                {"id": "TIME_PERIOD", "values": [
                    {"id": "2024-10"}, {"id": "2024-11"}, {"id": "2024-12"},
                ]}
            ]}}
        }
        result = ECBClient._parse_json(
            data, series_id="ECB_EA_M1", dataflow="BSI", limit=100,
        )
        self.assertEqual(len(result), 2)
        self.assertAlmostEqual(result[0].value, 16700000.0)
        self.assertAlmostEqual(result[1].value, 16500000.0)

    def test_empty_dataset(self):
        result = ECBClient._parse_json(
            EMPTY_JSON, series_id="ECB_EA_M1", dataflow="BSI", limit=100,
        )
        self.assertEqual(result, [])

    def test_limits_results(self):
        result = ECBClient._parse_json(
            SAMPLE_JSON, series_id="ECB_EA_M1", dataflow="BSI", limit=2,
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].date, "2024-12-01")
        self.assertEqual(result[1].date, "2024-11-01")


class TestNormalizeDate(unittest.TestCase):
    def test_monthly(self):
        self.assertEqual(_normalize_date("2024-01"), "2024-01-01")
        self.assertEqual(_normalize_date("2024-12"), "2024-12-01")

    def test_quarterly(self):
        self.assertEqual(_normalize_date("2024-Q1"), "2024-01-01")
        self.assertEqual(_normalize_date("2024-Q2"), "2024-04-01")
        self.assertEqual(_normalize_date("2024-Q3"), "2024-07-01")
        self.assertEqual(_normalize_date("2024-Q4"), "2024-10-01")

    def test_daily_passthrough(self):
        self.assertEqual(_normalize_date("2024-01-23"), "2024-01-23")

    def test_annual(self):
        self.assertEqual(_normalize_date("2024"), "2024-01-01")


class TestGetData(unittest.TestCase):
    def test_constructs_url(self):
        client = ECBClient.__new__(ECBClient)
        client.session = MagicMock()

        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = SAMPLE_JSON
        client.session.get.return_value = resp

        client.get_data("BSI", "M.U2.Y.V.M10.X.I.U2.2300.Z01.E", series_id="ECB_EA_M1")
        args, kwargs = client.session.get.call_args
        url = args[0]
        self.assertIn("data-api.ecb.europa.eu", url)
        self.assertIn("/BSI/M.U2.Y.V.M10.X.I.U2.2300.Z01.E", url)


if __name__ == "__main__":
    unittest.main()
