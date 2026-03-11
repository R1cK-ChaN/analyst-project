"""Unit tests for the FRED/ALFRED client."""

import unittest
from unittest.mock import MagicMock, patch

from analyst.ingestion.scrapers.fred import (
    FredClient,
    FredObservation,
    FredVintageObservation,
)


class TestFredGetSeries(unittest.TestCase):
    def test_parses_observations(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "observations": [
                {"date": "2026-03-10", "value": "4.25"},
                {"date": "2026-03-07", "value": "4.30"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        client = FredClient(api_key="test-key")
        client.session = MagicMock()
        client.session.get.return_value = mock_response

        result = client.get_series("DGS10", start_date="2026-03-01", limit=5)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], FredObservation)
        self.assertEqual(result[0].series_id, "DGS10")
        self.assertEqual(result[0].date, "2026-03-10")
        self.assertAlmostEqual(result[0].value, 4.25)

    def test_skips_missing_values(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "observations": [
                {"date": "2026-03-10", "value": "."},
                {"date": "2026-03-09", "value": "4.30"},
                {"date": "2026-03-08", "value": "."},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        client = FredClient(api_key="test-key")
        client.session = MagicMock()
        client.session.get.return_value = mock_response

        result = client.get_series("DGS10", start_date="2026-03-01")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].date, "2026-03-09")

    def test_returns_empty_without_api_key(self):
        client = FredClient(api_key="")
        result = client.get_series("DGS10", start_date="2026-03-01")
        self.assertEqual(result, [])

    def test_empty_response(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"observations": []}
        mock_response.raise_for_status = MagicMock()

        client = FredClient(api_key="test-key")
        client.session = MagicMock()
        client.session.get.return_value = mock_response

        result = client.get_series("DGS10", start_date="2026-03-01")
        self.assertEqual(result, [])


class TestFredGetSeriesInfo(unittest.TestCase):
    def test_returns_series_metadata(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "seriess": [{
                "id": "DGS10",
                "title": "Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity",
                "frequency": "Daily",
                "units": "Percent",
            }]
        }
        mock_response.raise_for_status = MagicMock()

        client = FredClient(api_key="test-key")
        client.session = MagicMock()
        client.session.get.return_value = mock_response

        info = client.get_series_info("DGS10")
        self.assertEqual(info["id"], "DGS10")
        self.assertIn("title", info)

    def test_returns_empty_dict_without_key(self):
        client = FredClient(api_key="")
        self.assertEqual(client.get_series_info("DGS10"), {})


class TestFredSearchSeries(unittest.TestCase):
    def test_returns_search_results(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "seriess": [
                {"id": "DGS10", "title": "10-Year Treasury"},
                {"id": "DGS2", "title": "2-Year Treasury"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        client = FredClient(api_key="test-key")
        client.session = MagicMock()
        client.session.get.return_value = mock_response

        results = client.search_series("treasury yield", limit=5)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["id"], "DGS10")


class TestFredGetVintages(unittest.TestCase):
    def test_parses_vintage_observations(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "observations": [
                {"date": "2025-10-01", "realtime_start": "2025-10-30", "value": "28538.1"},
                {"date": "2025-10-01", "realtime_start": "2025-11-26", "value": "28712.3"},
                {"date": "2025-10-01", "realtime_start": "2025-12-22", "value": "28714.0"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        client = FredClient(api_key="test-key")
        client.session = MagicMock()
        client.session.get.return_value = mock_response

        result = client.get_vintages("GDP", start_date="2025-01-01")
        self.assertEqual(len(result), 3)
        self.assertIsInstance(result[0], FredVintageObservation)
        self.assertEqual(result[0].series_id, "GDP")
        self.assertEqual(result[0].date, "2025-10-01")
        self.assertEqual(result[0].vintage_date, "2025-10-30")
        self.assertAlmostEqual(result[0].value, 28538.1)
        # Verify revision: same date, different vintage
        self.assertEqual(result[1].vintage_date, "2025-11-26")
        self.assertAlmostEqual(result[1].value, 28712.3)

    def test_passes_output_type_param(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"observations": []}
        mock_response.raise_for_status = MagicMock()

        client = FredClient(api_key="test-key")
        client.session = MagicMock()
        client.session.get.return_value = mock_response

        client.get_vintages("GDP", start_date="2025-01-01")
        call_kwargs = client.session.get.call_args
        self.assertEqual(call_kwargs.kwargs.get("params", call_kwargs[1].get("params", {})).get("output_type"), 2)

    def test_skips_missing_vintage_values(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "observations": [
                {"date": "2025-10-01", "realtime_start": "2025-10-30", "value": "."},
                {"date": "2025-10-01", "realtime_start": "2025-11-26", "value": "28712.3"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        client = FredClient(api_key="test-key")
        client.session = MagicMock()
        client.session.get.return_value = mock_response

        result = client.get_vintages("GDP", start_date="2025-01-01")
        self.assertEqual(len(result), 1)

    def test_returns_empty_without_api_key(self):
        client = FredClient(api_key="")
        result = client.get_vintages("GDP", start_date="2025-01-01")
        self.assertEqual(result, [])


class TestFredGetRevisionHistory(unittest.TestCase):
    def test_parses_revisions(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "observations": [
                {"date": "2025-07-01", "realtime_start": "2025-07-30", "value": "27600.0"},
                {"date": "2025-07-01", "realtime_start": "2025-08-28", "value": "27850.5"},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        client = FredClient(api_key="test-key")
        client.session = MagicMock()
        client.session.get.return_value = mock_response

        result = client.get_revision_history("GDP", "2025-07-01")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].date, "2025-07-01")
        self.assertEqual(result[1].date, "2025-07-01")
        self.assertNotEqual(result[0].vintage_date, result[1].vintage_date)


if __name__ == "__main__":
    unittest.main()
