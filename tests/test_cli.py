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
from analyst.delivery.user_chat import UserChatReply
from analyst.engine.live_types import AgentTool
from analyst.ingestion.scrapers.oecd import OECDDataflow, OECDStructureSummary
from analyst.ingestion.sources import OECDSeriesConfig
from analyst.memory import ClientProfileUpdate
from analyst.memory import CompanionScheduleUpdate


class UserChatCLITest(unittest.TestCase):
    def test_companion_chat_once_prints_reply_and_records_interaction(self) -> None:
        fake_store = Mock()
        output = io.StringIO()

        with patch("analyst.cli.build_companion_services", return_value=(Mock(), [], fake_store)):
            with patch("analyst.cli.build_chat_context", return_value="memory block"):
                with patch(
                    "analyst.cli.generate_chat_reply",
                    return_value=UserChatReply(
                        text="先别急，今晚数据出来再看。",
                        profile_update=ClientProfileUpdate(confidence="中"),
                    ),
                ):
                    with patch("analyst.cli.record_chat_interaction") as record_mock:
                        with redirect_stdout(output):
                            rc = main(["companion-chat", "--once", "最近太难做了"])

        self.assertEqual(rc, 0)
        rendered = output.getvalue()
        self.assertIn("assistant>", rendered)
        self.assertIn("先别急，今晚数据出来再看。", rendered)
        record_mock.assert_called_once()

    def test_companion_chat_once_threads_schedule_context_and_update(self) -> None:
        fake_store = Mock()
        output = io.StringIO()

        with patch("analyst.cli.build_companion_services", return_value=(Mock(), [], fake_store)):
            with patch("analyst.cli.build_chat_context", return_value="memory block"):
                with patch("analyst.cli.build_companion_schedule_context", return_value="schedule block"):
                    with patch(
                        "analyst.cli.generate_chat_reply",
                        return_value=UserChatReply(
                            text="中午我应该去吃牛肉饭。",
                            profile_update=ClientProfileUpdate(),
                            schedule_update=CompanionScheduleUpdate(
                                revision_mode="set",
                                lunch_plan="beef rice",
                            ),
                        ),
                    ) as reply_mock:
                        with patch("analyst.cli.apply_companion_schedule_update") as schedule_mock:
                            with patch("analyst.cli.record_chat_interaction"):
                                with redirect_stdout(output):
                                    rc = main(["companion-chat", "--once", "中午准备干嘛？"])

        self.assertEqual(rc, 0)
        self.assertEqual(
            reply_mock.call_args.kwargs["companion_local_context"],
            "schedule block",
        )
        schedule_mock.assert_called_once()

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


    def test_media_gen_image_selfie_mode_copies_persona_image_into_output_dir(self) -> None:
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "persona_selfie.jpg"
            source_path.write_bytes(b"selfie-bytes")
            output_dir = Path(tmpdir) / "artifacts"

            image_tool = AgentTool(
                name="generate_image",
                description="",
                parameters={},
                handler=lambda arguments: {
                    "status": "ok",
                    "image_path": str(source_path),
                    "prompt_used": "young Chinese male, iphone front camera selfie, holding a coffee cup",
                    "mode": "selfie",
                    "scene_key": "coffee_shop",
                    "scene_prompt": "holding a coffee cup near the camera",
                },
            )

            with patch("analyst.cli.build_image_gen_tool", return_value=image_tool):
                with redirect_stdout(output):
                    rc = main(
                        [
                            "media-gen",
                            "image",
                            "--mode",
                            "selfie",
                            "--scene-key",
                            "coffee_shop",
                            "--output-dir",
                            str(output_dir),
                        ]
                    )

            self.assertEqual(rc, 0)
            self.assertTrue((output_dir / "image.jpg").is_file())
            self.assertTrue((output_dir / "result.json").is_file())
            import json

            manifest = json.loads((output_dir / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["result"]["mode"], "selfie")
            self.assertEqual(manifest["result"]["scene_key"], "coffee_shop")
            self.assertIn("image_path", manifest["saved_artifacts"])

    def test_media_gen_image_json_flag_prints_manifest_to_stdout(self) -> None:
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
                    "prompt_used": "a market chart",
                },
            )

            with patch("analyst.cli.build_image_gen_tool", return_value=image_tool):
                with redirect_stdout(output):
                    rc = main(
                        [
                            "media-gen",
                            "image",
                            "--prompt",
                            "a market chart",
                            "--output-dir",
                            str(output_dir),
                            "--json",
                        ]
                    )

            self.assertEqual(rc, 0)
            import json

            printed = json.loads(output.getvalue())
            self.assertIn("output_dir", printed)
            self.assertIn("saved_artifacts", printed)
            self.assertIn("result", printed)
            self.assertEqual(printed["result"]["status"], "ok")

    def test_media_gen_image_selfie_with_scene_prompt_override(self) -> None:
        captured_args: list[dict] = []
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = Path(tmpdir) / "selfie.jpg"
            source_path.write_bytes(b"selfie-bytes")
            output_dir = Path(tmpdir) / "artifacts"

            def fake_handler(arguments: dict) -> dict:
                captured_args.append(dict(arguments))
                return {
                    "status": "ok",
                    "image_path": str(source_path),
                    "prompt_used": "assembled prompt",
                    "mode": "selfie",
                    "scene_key": "night_walk",
                    "scene_prompt": "wearing a leather jacket under neon lights",
                }

            image_tool = AgentTool(
                name="generate_image",
                description="",
                parameters={},
                handler=fake_handler,
            )

            with patch("analyst.cli.build_image_gen_tool", return_value=image_tool):
                with redirect_stdout(output):
                    rc = main(
                        [
                            "media-gen",
                            "image",
                            "--mode",
                            "selfie",
                            "--scene-key",
                            "night_walk",
                            "--scene-prompt",
                            "wearing a leather jacket under neon lights",
                            "--output-dir",
                            str(output_dir),
                        ]
                    )

            self.assertEqual(rc, 0)
            self.assertEqual(len(captured_args), 1)
            self.assertEqual(captured_args[0]["mode"], "selfie")
            self.assertEqual(captured_args[0]["scene_key"], "night_walk")
            self.assertEqual(
                captured_args[0]["scene_prompt"],
                "wearing a leather jacket under neon lights",
            )

    def test_oecd_dataflows_command_prints_matches(self) -> None:
        output = io.StringIO()
        fake_ingestion = Mock()
        fake_ingestion.list_catalog_dataflows.return_value = [
            OECDDataflow(
                id="DSD_STES@DF_CLI",
                agency_id="OECD.SDD.STES",
                version="4.1",
                name="Composite leading indicators",
            )
        ]
        with patch("analyst.macro_data.cli.OECDIngestionClient", return_value=fake_ingestion):
            with redirect_stdout(output):
                rc = main(["oecd-dataflows", "--limit", "1"])

        self.assertEqual(rc, 0)
        rendered = output.getvalue()
        self.assertIn("OECD.SDD.STES", rendered)
        self.assertIn("DSD_STES@DF_CLI", rendered)

    def test_oecd_structure_command_prints_json_summary(self) -> None:
        output = io.StringIO()
        fake_ingestion = Mock()
        fake_ingestion.get_structure_summary.return_value = OECDStructureSummary(
            dataflow_id="DSD_STES@DF_CLI",
            agency_id="OECD.SDD.STES",
            version="4.1",
            name="Composite leading indicators",
            structure_id="DSD_STES",
            time_dimension_id="TIME_PERIOD",
            series_dimensions=("REF_AREA", "FREQ", "MEASURE"),
            code_counts={"REF_AREA": 2},
            defaults={"FREQ": "M"},
        )
        with patch("analyst.macro_data.cli.OECDIngestionClient", return_value=fake_ingestion):
            with redirect_stdout(output):
                rc = main(["oecd-structure", "--dataflow", "DSD_STES@DF_CLI"])

        self.assertEqual(rc, 0)
        import json

        payload = json.loads(output.getvalue())
        self.assertEqual(payload["dataflow_id"], "DSD_STES@DF_CLI")
        self.assertEqual(payload["time_dimension_id"], "TIME_PERIOD")

    def test_oecd_generate_configs_command_prints_python_snippet(self) -> None:
        output = io.StringIO()
        fake_ingestion = Mock()
        fake_ingestion.generate_catalog_series_configs.return_value = {
            "auto_cli": OECDSeriesConfig(
                dataflow="DSD_STES@DF_CLI",
                series_id="OECD_AUTO_DSD_STES_DF_CLI_ABCDEF123456",
                category="catalog",
                agency_id="OECD.SDD.STES",
                version="4.1",
                filters={"REF_AREA": "USA", "FREQ": "M"},
            )
        }
        with patch("analyst.macro_data.cli.OECDIngestionClient", return_value=fake_ingestion):
            with redirect_stdout(output):
                rc = main(["oecd-generate-configs", "--dataflow-limit", "1", "--series-per-dataflow", "1"])

        self.assertEqual(rc, 0)
        rendered = output.getvalue()
        self.assertIn("generated_oecd_series = {", rendered)
        self.assertIn('"auto_cli": OECDSeriesConfig(', rendered)

    def test_oecd_refresh_catalog_command_prints_counts(self) -> None:
        output = io.StringIO()
        fake_ingestion = Mock()
        fake_ingestion.refresh_catalog.return_value = Mock(source="oecd_catalog", count=12)
        fake_store = Mock()
        with patch("analyst.macro_data.cli.OECDIngestionClient", return_value=fake_ingestion):
            with patch("analyst.storage.SQLiteEngineStore", return_value=fake_store):
                with redirect_stdout(output):
                    rc = main(["oecd-refresh-catalog", "--dataflow-limit", "1", "--sleep-seconds", "0"])

        self.assertEqual(rc, 0)
        self.assertIn("oecd_catalog", output.getvalue())


if __name__ == "__main__":
    unittest.main()
