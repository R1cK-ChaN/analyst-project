"""Unit tests for the World Bank REST API client."""

import unittest
from unittest.mock import MagicMock

from analyst.ingestion.scrapers.worldbank import (
    WorldBankClient,
    WorldBankObservation,
    _normalize_date,
)


SAMPLE_RESPONSE = [
    {"page": 1, "pages": 1, "per_page": 50, "total": 3},
    [
        {"indicator": {"id": "NY.GDP.PCAP.PP.CD"}, "country": {"id": "US"}, "countryiso3code": "USA", "date": "2023", "value": 85000.5},
        {"indicator": {"id": "NY.GDP.PCAP.PP.CD"}, "country": {"id": "US"}, "countryiso3code": "USA", "date": "2022", "value": 80000.0},
        {"indicator": {"id": "NY.GDP.PCAP.PP.CD"}, "country": {"id": "US"}, "countryiso3code": "USA", "date": "2021", "value": 75000.0},
    ]
]

EMPTY_RESPONSE = [
    {"page": 1, "pages": 0, "per_page": 50, "total": 0},
    None,
]


class TestParseJson(unittest.TestCase):
    def test_parses_response(self):
        result = WorldBankClient._parse_json(
            SAMPLE_RESPONSE, series_id="WB_GDP_PCAP_US", indicator="NY.GDP.PCAP.PP.CD", limit=50,
        )
        self.assertEqual(len(result), 3)
        self.assertIsInstance(result[0], WorldBankObservation)
        self.assertEqual(result[0].indicator, "NY.GDP.PCAP.PP.CD")
        self.assertTrue(all(obs.series_id == "WB_GDP_PCAP_US" for obs in result))
        # Sorted descending
        self.assertEqual(result[0].date, "2023-01-01")
        self.assertAlmostEqual(result[0].value, 85000.5)
        self.assertEqual(result[1].date, "2022-01-01")
        self.assertEqual(result[2].date, "2021-01-01")

    def test_skips_null_values(self):
        data = [
            {"page": 1, "pages": 1, "per_page": 50, "total": 3},
            [
                {"indicator": {"id": "X"}, "country": {"id": "US"}, "date": "2023", "value": 85000.5},
                {"indicator": {"id": "X"}, "country": {"id": "US"}, "date": "2022", "value": None},
                {"indicator": {"id": "X"}, "country": {"id": "US"}, "date": "2021", "value": 75000.0},
            ]
        ]
        result = WorldBankClient._parse_json(
            data, series_id="WB_GDP_PCAP_US", indicator="X", limit=50,
        )
        self.assertEqual(len(result), 2)
        self.assertAlmostEqual(result[0].value, 85000.5)
        self.assertAlmostEqual(result[1].value, 75000.0)

    def test_empty_response(self):
        result = WorldBankClient._parse_json(
            EMPTY_RESPONSE, series_id="WB_GDP_PCAP_US", indicator="X", limit=50,
        )
        self.assertEqual(result, [])

    def test_limits_results(self):
        result = WorldBankClient._parse_json(
            SAMPLE_RESPONSE, series_id="WB_GDP_PCAP_US", indicator="NY.GDP.PCAP.PP.CD", limit=2,
        )
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].date, "2023-01-01")
        self.assertEqual(result[1].date, "2022-01-01")


class TestNormalizeDate(unittest.TestCase):
    def test_annual(self):
        self.assertEqual(_normalize_date("2023"), "2023-01-01")
        self.assertEqual(_normalize_date("2000"), "2000-01-01")

    def test_passthrough(self):
        self.assertEqual(_normalize_date("2023-06-15"), "2023-06-15")


class TestGetIndicator(unittest.TestCase):
    def test_constructs_url(self):
        client = WorldBankClient.__new__(WorldBankClient)
        client.session = MagicMock()

        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = SAMPLE_RESPONSE
        client.session.get.return_value = resp

        client.get_indicator(
            "NY.GDP.PCAP.PP.CD", "USA", series_id="WB_GDP_PCAP_US",
        )
        args, kwargs = client.session.get.call_args
        url = args[0]
        self.assertIn("api.worldbank.org/v2", url)
        self.assertIn("/country/USA/indicator/NY.GDP.PCAP.PP.CD", url)


if __name__ == "__main__":
    unittest.main()
