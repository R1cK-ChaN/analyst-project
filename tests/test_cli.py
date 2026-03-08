from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst.cli import main
from analyst.delivery.sales_chat import SalesChatReply
from analyst.memory import ClientProfileUpdate


class SalesChatCLITest(unittest.TestCase):
    def test_sales_chat_once_prints_reply_and_records_interaction(self) -> None:
        fake_store = Mock()
        output = io.StringIO()

        with patch("analyst.cli.build_sales_services", return_value=(Mock(), [], fake_store)):
            with patch("analyst.cli.build_sales_context", return_value="memory block"):
                with patch(
                    "analyst.cli.generate_sales_reply",
                    return_value=SalesChatReply(
                        text="先别急，今晚数据出来再看。",
                        profile_update=ClientProfileUpdate(confidence="中"),
                    ),
                ):
                    with patch("analyst.cli.record_sales_interaction") as record_mock:
                        with redirect_stdout(output):
                            rc = main(["sales-chat", "--once", "最近太难做了"])

        self.assertEqual(rc, 0)
        rendered = output.getvalue()
        self.assertIn("assistant>", rendered)
        self.assertIn("先别急，今晚数据出来再看。", rendered)
        record_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
