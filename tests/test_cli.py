from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst.cli import main
from analyst.delivery.sales_chat import SalesChatReply
from analyst.engine.live_types import AgentTool
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

    def test_media_gen_image_copies_generated_image_into_output_dir(self) -> None:
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "source.png"
            source_path.write_bytes(b"image-bytes")
            output_dir = Path(tmpdir) / "artifacts"

            image_tool = AgentTool(
                name="generate_image",
                description="",
                parameters={},
                handler=lambda arguments: {
                    "status": "ok",
                    "image_path": str(source_path),
                    "prompt_used": "coffee cup on a desk",
                },
            )

            with patch("analyst.cli.build_image_gen_tool", return_value=image_tool):
                with redirect_stdout(output):
                    rc = main(
                        [
                            "media-gen",
                            "image",
                            "--prompt",
                            "coffee cup on a desk",
                            "--output-dir",
                            str(output_dir),
                        ]
                    )

            self.assertEqual(rc, 0)
            self.assertTrue((output_dir / "image.png").is_file())
            self.assertTrue((output_dir / "result.json").is_file())
            manifest = (output_dir / "result.json").read_text(encoding="utf-8")
            self.assertIn("image_path", manifest)

    def test_media_gen_live_photo_copies_motion_video_into_output_dir(self) -> None:
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "motion.mp4"
            source_path.write_bytes(b"video-bytes")
            output_dir = Path(tmpdir) / "artifacts"

            motion_tool = AgentTool(
                name="generate_live_photo",
                description="",
                parameters={},
                handler=lambda arguments: {
                    "status": "ok",
                    "fallback_kind": "video",
                    "delivery_video_path": str(source_path),
                    "prompt_used": "dynamic selfie in a coffee shop",
                },
            )

            with patch("analyst.cli.build_live_photo_tool", return_value=motion_tool):
                with redirect_stdout(output):
                    rc = main(
                        [
                            "media-gen",
                            "live-photo",
                            "--prompt",
                            "dynamic selfie in a coffee shop",
                            "--output-dir",
                            str(output_dir),
                        ]
                    )

            self.assertEqual(rc, 0)
            self.assertTrue((output_dir / "motion.mp4").is_file())
            self.assertTrue((output_dir / "result.json").is_file())
            manifest = (output_dir / "result.json").read_text(encoding="utf-8")
            self.assertIn("delivery_video_path", manifest)


if __name__ == "__main__":
    unittest.main()
