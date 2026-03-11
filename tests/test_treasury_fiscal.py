"""Unit tests for the Treasury Fiscal Data API client."""

import unittest
from unittest.mock import MagicMock

from analyst.ingestion.scrapers.treasury_fiscal import (
    TreasuryFiscalClient,
    TreasuryFiscalObservation,
)


class TestTreasuryGetDataset(unittest.TestCase):
    def test_returns_data_rows(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"record_date": "2026-03-10", "tot_pub_debt_out_amt": "36500000000000"},
                {"record_date": "2026-03-07", "tot_pub_debt_out_amt": "36480000000000"},
            ],
            "meta": {"count": 2, "total-count": 100},
        }
        mock_response.raise_for_status = MagicMock()

        client = TreasuryFiscalClient()
        client.session = MagicMock()
        client.session.get.return_value = mock_response

        rows = client.get_dataset(
            "v2/accounting/od/debt_to_penny",
            fields="record_date,tot_pub_debt_out_amt",
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["record_date"], "2026-03-10")

    def test_passes_filter_param(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": []}
        mock_response.raise_for_status = MagicMock()

        client = TreasuryFiscalClient()
        client.session = MagicMock()
        client.session.get.return_value = mock_response

        client.get_dataset(
            "v1/accounting/dts/deposits_withdrawals_operating_cash",
            filter_str="account_type:eq:Federal Reserve Account",
        )
        call_args = client.session.get.call_args
        params = call_args.kwargs.get("params") or call_args[1].get("params", {})
        self.assertEqual(params.get("filter"), "account_type:eq:Federal Reserve Account")

    def test_empty_response(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": []}
        mock_response.raise_for_status = MagicMock()

        client = TreasuryFiscalClient()
        client.session = MagicMock()
        client.session.get.return_value = mock_response

        rows = client.get_dataset("v2/accounting/od/debt_to_penny")
        self.assertEqual(rows, [])


class TestFetchDebtOutstanding(unittest.TestCase):
    def test_parses_debt_observations(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {
                    "record_date": "2026-03-10",
                    "debt_held_public_amt": "28000000000000",
                    "intragov_hold_amt": "7000000000000",
                    "tot_pub_debt_out_amt": "36500000000000",
                },
                {
                    "record_date": "2026-03-07",
                    "debt_held_public_amt": "27900000000000",
                    "intragov_hold_amt": "6900000000000",
                    "tot_pub_debt_out_amt": "36480000000000",
                },
            ],
        }
        mock_response.raise_for_status = MagicMock()

        client = TreasuryFiscalClient()
        client.session = MagicMock()
        client.session.get.return_value = mock_response

        result = client.fetch_debt_outstanding(limit=5)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], TreasuryFiscalObservation)
        self.assertEqual(result[0].series_id, "TREAS_DEBT_TOTAL")
        self.assertEqual(result[0].date, "2026-03-10")
        self.assertAlmostEqual(result[0].value, 36500000000000)
        self.assertIn("debt_held_public", result[0].metadata)

    def test_skips_empty_values(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {
                    "record_date": "2026-03-10",
                    "debt_held_public_amt": "",
                    "intragov_hold_amt": "",
                    "tot_pub_debt_out_amt": "",
                },
                {
                    "record_date": "2026-03-07",
                    "debt_held_public_amt": "27900000000000",
                    "intragov_hold_amt": "6900000000000",
                    "tot_pub_debt_out_amt": "36480000000000",
                },
            ],
        }
        mock_response.raise_for_status = MagicMock()

        client = TreasuryFiscalClient()
        client.session = MagicMock()
        client.session.get.return_value = mock_response

        result = client.fetch_debt_outstanding()
        self.assertEqual(len(result), 1)


class TestFetchTGABalance(unittest.TestCase):
    def test_parses_tga_observations(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {
                    "record_date": "2026-03-10",
                    "account_type": "Treasury General Account (TGA) Closing Balance",
                    "open_today_bal": "858548",
                },
            ],
        }
        mock_response.raise_for_status = MagicMock()

        client = TreasuryFiscalClient()
        client.session = MagicMock()
        client.session.get.return_value = mock_response

        result = client.fetch_tga_balance(limit=5)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].series_id, "TREAS_TGA_BALANCE")
        self.assertAlmostEqual(result[0].value, 858548)
        self.assertEqual(
            result[0].metadata["account_type"],
            "Treasury General Account (TGA) Closing Balance",
        )

    def test_skips_null_string_values(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {
                    "record_date": "2026-03-10",
                    "account_type": "Treasury General Account (TGA) Closing Balance",
                    "open_today_bal": "null",
                },
            ],
        }
        mock_response.raise_for_status = MagicMock()

        client = TreasuryFiscalClient()
        client.session = MagicMock()
        client.session.get.return_value = mock_response

        result = client.fetch_tga_balance()
        self.assertEqual(len(result), 0)


class TestFetchAvgInterestRates(unittest.TestCase):
    def test_parses_rate_observations(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {
                    "record_date": "2026-02-28",
                    "security_desc": "Treasury Bills",
                    "avg_interest_rate_amt": "4.875",
                },
                {
                    "record_date": "2026-02-28",
                    "security_desc": "Treasury Notes",
                    "avg_interest_rate_amt": "3.125",
                },
            ],
        }
        mock_response.raise_for_status = MagicMock()

        client = TreasuryFiscalClient()
        client.session = MagicMock()
        client.session.get.return_value = mock_response

        result = client.fetch_avg_interest_rates(limit=5)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].series_id, "TREAS_AVG_RATE")
        self.assertAlmostEqual(result[0].value, 4.875)
        self.assertEqual(result[0].metadata["security_desc"], "Treasury Bills")

    def test_skips_null_rates(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {
                    "record_date": "2026-02-28",
                    "security_desc": "Treasury Bills",
                    "avg_interest_rate_amt": None,
                },
            ],
        }
        mock_response.raise_for_status = MagicMock()

        client = TreasuryFiscalClient()
        client.session = MagicMock()
        client.session.get.return_value = mock_response

        result = client.fetch_avg_interest_rates()
        self.assertEqual(len(result), 0)


if __name__ == "__main__":
    unittest.main()
