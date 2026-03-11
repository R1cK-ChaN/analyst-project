"""Unit tests for the EIA API client."""

import unittest
from unittest.mock import MagicMock, patch

from analyst.ingestion.scrapers.eia import EIAClient, EIAObservation


class TestEIAGetSeries(unittest.TestCase):
    def test_parses_observations(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "response": {
                "data": [
                    {"period": "2026-03-10", "value": 72.50, "units": "$/bbl"},
                    {"period": "2026-03-07", "value": 71.80, "units": "$/bbl"},
                ],
                "total": 2,
            },
            "request": {},
        }
        mock_response.raise_for_status = MagicMock()

        client = EIAClient(api_key="test-key")
        client.session = MagicMock()
        client.session.get.return_value = mock_response

        result = client.get_series(
            "petroleum/pri/spt/data",
            params={"data[]": "value", "facets[product][]": "EPCBRENT", "frequency": "daily"},
            series_id="EIA_BRENT",
            limit=5,
        )
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], EIAObservation)
        self.assertEqual(result[0].series_id, "EIA_BRENT")
        self.assertEqual(result[0].date, "2026-03-10")
        self.assertAlmostEqual(result[0].value, 72.50)
        self.assertEqual(result[0].unit, "$/bbl")

    def test_skips_null_values(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "response": {
                "data": [
                    {"period": "2026-03-10", "value": None, "units": "$/bbl"},
                    {"period": "2026-03-09", "value": "", "units": "$/bbl"},
                    {"period": "2026-03-08", "value": 70.00, "units": "$/bbl"},
                ],
            },
        }
        mock_response.raise_for_status = MagicMock()

        client = EIAClient(api_key="test-key")
        client.session = MagicMock()
        client.session.get.return_value = mock_response

        result = client.get_series(
            "petroleum/pri/spt/data",
            params={"data[]": "value"},
            series_id="EIA_WTI",
        )
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0].value, 70.00)

    @patch("analyst.ingestion.scrapers.eia.get_env_value", return_value="")
    def test_returns_empty_without_api_key(self, _mock_env):
        client = EIAClient(api_key="")
        result = client.get_series(
            "petroleum/pri/spt/data",
            params={"data[]": "value"},
            series_id="EIA_WTI",
        )
        self.assertEqual(result, [])

    def test_empty_response(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": {"data": []}}
        mock_response.raise_for_status = MagicMock()

        client = EIAClient(api_key="test-key")
        client.session = MagicMock()
        client.session.get.return_value = mock_response

        result = client.get_series(
            "petroleum/pri/spt/data",
            params={"data[]": "value"},
            series_id="EIA_WTI",
        )
        self.assertEqual(result, [])

    def test_passes_start_param(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"response": {"data": []}}
        mock_response.raise_for_status = MagicMock()

        client = EIAClient(api_key="test-key")
        client.session = MagicMock()
        client.session.get.return_value = mock_response

        client.get_series(
            "petroleum/pri/spt/data",
            params={"data[]": "value"},
            series_id="EIA_BRENT",
            start="2026-01-01",
        )
        call_args = client.session.get.call_args
        params = call_args.kwargs.get("params") or call_args[1].get("params", {})
        self.assertEqual(params.get("start"), "2026-01-01")

    def test_handles_missing_units_field(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "response": {
                "data": [
                    {"period": "2026-03-10", "value": 100.0},
                ],
            },
        }
        mock_response.raise_for_status = MagicMock()

        client = EIAClient(api_key="test-key")
        client.session = MagicMock()
        client.session.get.return_value = mock_response

        result = client.get_series(
            "natural-gas/pri/fut/data",
            params={"data[]": "value"},
            series_id="EIA_NATGAS",
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].unit, "")


class TestEIAGetMetadata(unittest.TestCase):
    def test_returns_metadata(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "response": {"id": "petroleum", "name": "Petroleum"},
        }
        mock_response.raise_for_status = MagicMock()

        client = EIAClient(api_key="test-key")
        client.session = MagicMock()
        client.session.get.return_value = mock_response

        result = client.get_metadata("petroleum")
        self.assertIn("response", result)

    @patch("analyst.ingestion.scrapers.eia.get_env_value", return_value="")
    def test_returns_empty_without_key(self, _mock_env):
        client = EIAClient(api_key="")
        self.assertEqual(client.get_metadata("petroleum"), {})


if __name__ == "__main__":
    unittest.main()
