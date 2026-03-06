from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst import build_demo_app
from analyst.contracts import InteractionMode
from analyst.integration import detect_mode


class ProductLayerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.app = build_demo_app()

    def test_detect_mode_routes_draft(self) -> None:
        self.assertEqual(
            detect_mode("帮我写一段关于今晚非农数据的客户消息"),
            InteractionMode.DRAFT,
        )

    def test_end_to_end_draft_reply_contains_compliance_notice(self) -> None:
        reply = self.app.route(
            "帮我写一段关于今晚非农数据的客户消息",
            user_id="rm-001",
        )
        self.assertEqual(reply.mode, InteractionMode.DRAFT)
        self.assertIn("客户消息初稿", reply.markdown)
        self.assertIn("合规提示", reply.markdown)

    def test_end_to_end_regime_reply_contains_scores(self) -> None:
        reply = self.app.route(
            "现在宏观整体怎么看？",
            user_id="rm-002",
        )
        self.assertEqual(reply.mode, InteractionMode.REGIME)
        self.assertIn("分项评分", reply.markdown)
        self.assertIn("宏观状态摘要", reply.markdown)

    def test_premarket_briefing_is_built_from_product_contracts(self) -> None:
        note = self.app.premarket()
        payload = note.to_dict()
        self.assertEqual(note.note_type, "pre_market")
        self.assertIn("早盘速递", note.title)
        self.assertIn("今日要看", note.body_markdown)
        self.assertIn("created_at", payload)

    def test_calendar_reply_uses_local_data_files(self) -> None:
        reply = self.app.calendar(limit=2)
        self.assertEqual(reply.mode, InteractionMode.CALENDAR)
        self.assertIn("美国非农就业", reply.markdown)


if __name__ == "__main__":
    unittest.main()
