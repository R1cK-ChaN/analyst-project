"""Unit tests for the IMF SDMX 3.0 JSON API client."""

import unittest
from unittest.mock import MagicMock, call

from analyst.ingestion.scrapers.imf import (
    IMFClient,
    IMFObservation,
    IMFVintageObservation,
    _normalize_date,
)


SAMPLE_JSON = {
    "data": {
        "dataSets": [{"series": {"0:0:0:0:0:0": {"observations": {
            "0": [103.519], "1": [103.8396], "2": [104.1],
        }}}}],
        "structures": [{"dimensions": {"observation": [
            {"id": "TIME_PERIOD", "values": [
                {"value": "2025-M09"}, {"value": "2025-M10"}, {"value": "2025-M11"},
            ]}
        ]}}]
    }
}

EMPTY_JSON = {
    "data": {
        "dataSets": [{"series": {}}],
        "structures": [{"dimensions": {"observation": [
            {"id": "TIME_PERIOD", "values": []}
        ]}}]
    }
}

MULTI_SERIES_JSON = {
    "data": {
        "dataSets": [{"series": {
            "0:0:0:0:0:0": {"observations": {"0": [100.0], "1": [200.0]}},
            "0:0:0:0:0:1": {"observations": {"0": [300.0], "1": [400.0]}},
        }}],
        "structures": [{"dimensions": {"observation": [
            {"id": "TIME_PERIOD", "values": [
                {"value": "2024-Q1"}, {"value": "2024-Q2"},
            ]}
        ]}}]
    }
}


class TestParseJson(unittest.TestCase):
    def test_parses_json_response(self):
        result = IMFClient._parse_json(
            SAMPLE_JSON, series_id="IMF_CN_CPI", dataflow="CPI", limit=100,
        )
        self.assertEqual(len(result), 3)
        self.assertIsInstance(result[0], IMFObservation)
        self.assertEqual(result[0].dataflow, "CPI")
        self.assertTrue(all(obs.series_id == "IMF_CN_CPI" for obs in result))
        # Sorted descending
        self.assertEqual(result[0].date, "2025-11-01")
        self.assertAlmostEqual(result[0].value, 104.1)
        self.assertEqual(result[1].date, "2025-10-01")
        self.assertAlmostEqual(result[1].value, 103.8396)
        self.assertEqual(result[2].date, "2025-09-01")
        self.assertAlmostEqual(result[2].value, 103.519)

    def test_skips_null_values(self):
        data = {
            "data": {
                "dataSets": [{"series": {"0:0:0": {"observations": {
                    "0": [103.519], "1": [None], "2": [104.1],
                }}}}],
                "structures": [{"dimensions": {"observation": [
                    {"id": "TIME_PERIOD", "values": [
                        {"value": "2025-M09"}, {"value": "2025-M10"}, {"value": "2025-M11"},
                    ]}
                ]}}]
            }
        }
        result = IMFClient._parse_json(
            data, series_id="IMF_CN_CPI", dataflow="CPI", limit=100,
        )
        self.assertEqual(len(result), 2)
        self.assertAlmostEqual(result[0].value, 104.1)
        self.assertAlmostEqual(result[1].value, 103.519)

    def test_empty_dataset(self):
        result = IMFClient._parse_json(
            EMPTY_JSON, series_id="IMF_CN_CPI", dataflow="CPI", limit=100,
        )
        self.assertEqual(result, [])

    def test_limits_results(self):
        result = IMFClient._parse_json(
            SAMPLE_JSON, series_id="IMF_CN_CPI", dataflow="CPI", limit=2,
        )
        self.assertEqual(len(result), 2)
        # Should keep the most recent (descending sort, then slice)
        self.assertEqual(result[0].date, "2025-11-01")
        self.assertEqual(result[1].date, "2025-10-01")

    def test_multiple_series_keys(self):
        result = IMFClient._parse_json(
            MULTI_SERIES_JSON, series_id="IMF_CN_GDP", dataflow="QNEA", limit=100,
        )
        # 2 series × 2 obs = 4 observations
        self.assertEqual(len(result), 4)
        self.assertEqual(result[0].date, "2024-04-01")
        self.assertEqual(result[-1].date, "2024-01-01")


class TestNormalizeDate(unittest.TestCase):
    def test_normalizes_monthly_dates(self):
        self.assertEqual(_normalize_date("2025-M09"), "2025-09-01")
        self.assertEqual(_normalize_date("2024-M01"), "2024-01-01")
        self.assertEqual(_normalize_date("2025-M12"), "2025-12-01")

    def test_normalizes_quarterly_dates(self):
        self.assertEqual(_normalize_date("2024-Q1"), "2024-01-01")
        self.assertEqual(_normalize_date("2024-Q2"), "2024-04-01")
        self.assertEqual(_normalize_date("2024-Q3"), "2024-07-01")
        self.assertEqual(_normalize_date("2024-Q4"), "2024-10-01")

    def test_normalizes_legacy_dates(self):
        self.assertEqual(_normalize_date("2024-01"), "2024-01-01")
        self.assertEqual(_normalize_date("2024"), "2024-01-01")


class TestGetVintages(unittest.TestCase):
    def test_returns_vintage_observations(self):
        client = IMFClient.__new__(IMFClient)
        client.session = MagicMock()

        def make_response(as_of):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = {
                "data": {
                    "dataSets": [{"series": {"0:0:0:0:0:0": {"observations": {
                        "0": [30000.0],
                    }}}}],
                    "structures": [{"dimensions": {"observation": [
                        {"id": "TIME_PERIOD", "values": [
                            {"value": "2024-Q1"},
                        ]}
                    ]}}]
                }
            }
            return resp

        client.session.get.side_effect = [
            make_response("2025-06-01"),
            make_response("2026-03-01"),
        ]

        vints = client.get_vintages(
            "QNEA", "CHN.B1GQ.V.NSA.XDC.Q",
            series_id="IMF_CN_GDP", version="7.0.0",
            as_of_dates=["2025-06-01", "2026-03-01"],
            start_period="2024", limit=8,
        )
        self.assertEqual(len(vints), 2)
        self.assertIsInstance(vints[0], IMFVintageObservation)
        self.assertEqual(vints[0].vintage_date, "2025-06-01")
        self.assertEqual(vints[0].date, "2024-01-01")
        self.assertEqual(vints[0].series_id, "IMF_CN_GDP")
        self.assertEqual(vints[1].vintage_date, "2026-03-01")

    def test_passes_asof_param(self):
        client = IMFClient.__new__(IMFClient)
        client.session = MagicMock()

        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"data": {"dataSets": [{"series": {}}], "structures": [{"dimensions": {"observation": [{"id": "TIME_PERIOD", "values": []}]}}]}}
        client.session.get.return_value = resp

        client.get_vintages(
            "QNEA", "CHN.B1GQ.V.NSA.XDC.Q",
            series_id="IMF_CN_GDP", version="7.0.0",
            as_of_dates=["2025-06-01"],
        )
        args, kwargs = client.session.get.call_args
        self.assertIn("asOf", kwargs["params"])
        self.assertEqual(kwargs["params"]["asOf"], "2025-06-01")


class TestGetData(unittest.TestCase):
    def test_constructs_v3_url(self):
        client = IMFClient.__new__(IMFClient)
        client.session = MagicMock()

        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = SAMPLE_JSON
        client.session.get.return_value = resp

        client.get_data("CPI", "CHN.CPI._T.IX.M", series_id="IMF_CN_CPI", version="5.0.0")
        args, kwargs = client.session.get.call_args
        url = args[0]
        self.assertIn("/data/dataflow/IMF.STA/CPI/5.0.0/CHN.CPI._T.IX.M", url)
        self.assertIn("api.imf.org/external/sdmx/3.0", url)


if __name__ == "__main__":
    unittest.main()
