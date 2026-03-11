"""Unit tests for the BIS SDMX REST API client (CSV format)."""

import unittest
from unittest.mock import MagicMock

from analyst.ingestion.scrapers.bis import BISClient, BISObservation


CSV_HEADER = "FREQ,REF_AREA,TIME_PERIOD,OBS_VALUE\n"


class TestGetData(unittest.TestCase):
    def _make_client(self, csv_text: str) -> BISClient:
        mock_resp = MagicMock()
        mock_resp.text = csv_text
        mock_resp.raise_for_status = MagicMock()
        client = BISClient()
        client.session = MagicMock()
        client.session.get.return_value = mock_resp
        return client

    def test_parses_csv_response(self):
        csv_data = (
            CSV_HEADER
            + "M,US,2024-01,4.33\n"
            + "M,US,2024-02,4.58\n"
            + "M,US,2024-03,4.75\n"
        )
        client = self._make_client(csv_data)
        result = client.get_data("WS_CBPOL", "M.US", series_id="BIS_POLICY_US")
        self.assertEqual(len(result), 3)
        self.assertIsInstance(result[0], BISObservation)
        # Sorted descending — most recent first
        self.assertEqual(result[0].date, "2024-03-01")
        self.assertAlmostEqual(result[0].value, 4.75)
        self.assertEqual(result[0].series_id, "BIS_POLICY_US")
        self.assertEqual(result[0].dataflow, "WS_CBPOL")

    def test_skips_null_values(self):
        csv_data = (
            CSV_HEADER
            + "M,US,2024-01,4.33\n"
            + "M,US,2024-02,\n"
            + "M,US,2024-03,4.75\n"
        )
        client = self._make_client(csv_data)
        result = client.get_data("WS_CBPOL", "M.US", series_id="BIS_POLICY_US")
        self.assertEqual(len(result), 2)

    def test_normalizes_dates(self):
        csv_data = CSV_HEADER + "M,US,2024-01,4.33\n"
        client = self._make_client(csv_data)
        result = client.get_data("WS_CBPOL", "M.US", series_id="BIS_POLICY_US")
        self.assertEqual(result[0].date, "2024-01-01")

    def test_normalizes_quarterly_dates(self):
        csv_data = CSV_HEADER + "Q,US,2024-Q1,5.2\nQ,US,2024-Q3,5.5\n"
        client = self._make_client(csv_data)
        result = client.get_data("WS_CREDIT_GAP", "Q.US.P", series_id="BIS_CREDIT_GAP_US")
        dates = {obs.date for obs in result}
        self.assertIn("2024-01-01", dates)
        self.assertIn("2024-07-01", dates)

    def test_empty_response(self):
        client = self._make_client(CSV_HEADER)
        result = client.get_data("WS_CBPOL", "M.US", series_id="BIS_POLICY_US")
        self.assertEqual(result, [])

    def test_limits_results(self):
        lines = [f"M,US,20{20 + i // 12:02d}-{i % 12 + 1:02d},{float(i)}\n" for i in range(20)]
        csv_data = CSV_HEADER + "".join(lines)
        client = self._make_client(csv_data)
        result = client.get_data("WS_CBPOL", "M.US", series_id="BIS_POLICY_US", limit=5)
        self.assertEqual(len(result), 5)

    def test_multiple_series_rows(self):
        csv_data = (
            CSV_HEADER
            + "M,US,2024-01,4.33\n"
            + "M,JP,2024-01,0.10\n"
        )
        client = self._make_client(csv_data)
        result = client.get_data("WS_CBPOL", "M.US+JP", series_id="BIS_POLICY")
        self.assertEqual(len(result), 2)


if __name__ == "__main__":
    unittest.main()
