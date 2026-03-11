"""Unit tests for the Eurostat JSON-stat API client."""

import unittest
from unittest.mock import MagicMock

from analyst.ingestion.scrapers.eurostat import EurostatClient, EurostatObservation


class TestGetDataset(unittest.TestCase):
    def _make_client(self, json_payload: dict) -> EurostatClient:
        mock_resp = MagicMock()
        mock_resp.json.return_value = json_payload
        mock_resp.raise_for_status = MagicMock()
        client = EurostatClient()
        client.session = MagicMock()
        client.session.get.return_value = mock_resp
        return client

    def test_parses_json_stat_response(self):
        client = self._make_client({
            "dimension": {
                "time": {"category": {"index": {"2024M01": 0, "2024M02": 1, "2024M03": 2}}},
            },
            "value": {"0": 2.8, "1": 2.6, "2": 2.4},
        })
        result = client.get_dataset("prc_hicp_manr", series_id="ESTAT_HICP")
        self.assertEqual(len(result), 3)
        self.assertIsInstance(result[0], EurostatObservation)
        # Sorted descending — most recent first
        self.assertEqual(result[0].date, "2024-03-01")
        self.assertAlmostEqual(result[0].value, 2.4)
        self.assertEqual(result[-1].date, "2024-01-01")

    def test_skips_missing_values(self):
        client = self._make_client({
            "dimension": {
                "time": {"category": {"index": {"2024M01": 0, "2024M02": 1, "2024M03": 2}}},
            },
            "value": {"0": 2.8, "2": 2.4},
        })
        result = client.get_dataset("prc_hicp_manr", series_id="ESTAT_HICP")
        self.assertEqual(len(result), 2)
        dates = {obs.date for obs in result}
        self.assertNotIn("2024-02-01", dates)

    def test_skips_null_values(self):
        client = self._make_client({
            "dimension": {
                "time": {"category": {"index": {"2024M01": 0, "2024M02": 1}}},
            },
            "value": {"0": 2.8, "1": None},
        })
        result = client.get_dataset("prc_hicp_manr", series_id="ESTAT_HICP")
        self.assertEqual(len(result), 1)

    def test_normalizes_monthly_periods(self):
        client = self._make_client({
            "dimension": {
                "time": {"category": {"index": {"2024M01": 0}}},
            },
            "value": {"0": 2.8},
        })
        result = client.get_dataset("prc_hicp_manr", series_id="ESTAT_HICP")
        self.assertEqual(result[0].date, "2024-01-01")

    def test_normalizes_quarterly_periods(self):
        client = self._make_client({
            "dimension": {
                "time": {"category": {"index": {"2024Q1": 0, "2024Q3": 1}}},
            },
            "value": {"0": 0.3, "1": 0.5},
        })
        result = client.get_dataset("namq_10_gdp", series_id="ESTAT_GDP")
        dates = {obs.date for obs in result}
        self.assertIn("2024-01-01", dates)
        self.assertIn("2024-07-01", dates)

    def test_empty_response(self):
        client = self._make_client({
            "dimension": {"time": {"category": {"index": {}}}},
            "value": {},
        })
        result = client.get_dataset("prc_hicp_manr", series_id="ESTAT_HICP")
        self.assertEqual(result, [])

    def test_limits_results(self):
        index = {f"2024M{i:02d}": i - 1 for i in range(1, 13)}
        values = {str(i - 1): float(i) for i in range(1, 13)}
        client = self._make_client({
            "dimension": {"time": {"category": {"index": index}}},
            "value": values,
        })
        result = client.get_dataset("prc_hicp_manr", series_id="ESTAT_HICP", limit=5)
        self.assertEqual(len(result), 5)

    def test_dataset_field_set(self):
        client = self._make_client({
            "dimension": {
                "time": {"category": {"index": {"2024M01": 0}}},
            },
            "value": {"0": 2.8},
        })
        result = client.get_dataset("prc_hicp_manr", series_id="ESTAT_HICP")
        self.assertEqual(result[0].dataset, "prc_hicp_manr")


if __name__ == "__main__":
    unittest.main()
