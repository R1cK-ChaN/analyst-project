from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst.delivery.sales_chat import _extract_media
from analyst.engine.live_types import ConversationMessage
from analyst.tools._image_gen import ImageGenConfig
from analyst.tools._live_photo import (
    GeneratedVideo,
    LivePhotoHandler,
    LivePhotoPackager,
    LivePhotoPackagingConfig,
    SeedDanceConfig,
    SeedDanceVideoProvider,
    VideoGenerationError,
    build_optional_live_photo_tool,
)


class TestSeedDanceVideoProvider(unittest.TestCase):
    def test_generate_video_polls_then_downloads_clip(self) -> None:
        session = Mock()
        session.post.return_value = _json_response({"output": {"task_id": "task-123"}})

        poll_responses = [
            _json_response({"output": {"task_status": "RUNNING"}}),
            _json_response(
                {
                    "output": {
                        "task_status": "SUCCEEDED",
                        "content": [{"video_url": "https://example.com/generated.mp4"}],
                    },
                }
            ),
        ]

        def fake_get(url: str, **kwargs: object) -> Mock:
            if url.endswith("/task-123"):
                return poll_responses.pop(0)
            return _download_response(b"fake video bytes")

        session.get.side_effect = fake_get
        provider = SeedDanceVideoProvider(
            SeedDanceConfig(
                api_key="test-key",
                base_url="https://seedance.example/api/v3",
                model="seedance-test",
                poll_interval_seconds=0,
            ),
            session=session,
            sleep_fn=lambda _: None,
        )

        result = provider.generate_video(prompt="smiling at a desk", duration_seconds=3)

        self.assertTrue(result.video_path.endswith(".mp4"))
        self.assertTrue(Path(result.video_path).exists())
        self.assertEqual(Path(result.video_path).read_bytes(), b"fake video bytes")
        Path(result.video_path).unlink()

    def test_generate_video_accepts_top_level_content_video_url(self) -> None:
        session = Mock()
        session.post.return_value = _json_response({"id": "task-123"})

        poll_responses = [
            _json_response({"status": "running"}),
            _json_response(
                {
                    "status": "succeeded",
                    "content": {"video_url": "https://example.com/generated.mp4"},
                }
            ),
        ]

        def fake_get(url: str, **kwargs: object) -> Mock:
            if url.endswith("/task-123"):
                return poll_responses.pop(0)
            return _download_response(b"fake video bytes")

        session.get.side_effect = fake_get
        provider = SeedDanceVideoProvider(
            SeedDanceConfig(
                api_key="test-key",
                base_url="https://seedance.example/api/v3",
                model="seedance-test",
                poll_interval_seconds=0,
            ),
            session=session,
            sleep_fn=lambda _: None,
        )

        result = provider.generate_video(prompt="smiling at a desk", duration_seconds=3)

        self.assertEqual(result.video_url, "https://example.com/generated.mp4")
        Path(result.video_path).unlink()


class TestLivePhotoHandler(unittest.TestCase):
    def test_falls_back_to_static_image_when_motion_generation_fails(self) -> None:
        provider = Mock()
        provider.generate_video.side_effect = VideoGenerationError("timed out")
        packager = Mock()
        image_handler = Mock(return_value={"status": "ok", "image_path": "/tmp/fallback.png"})

        handler = LivePhotoHandler(provider, packager, image_handler)
        result = handler({"prompt": "dynamic selfie"})

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["fallback_kind"], "image")
        self.assertEqual(result["image_path"], "/tmp/fallback.png")

    def test_returns_video_when_packaging_is_unavailable(self) -> None:
        provider = Mock(return_value=None)
        provider.generate_video.return_value = GeneratedVideo(
            video_path="/tmp/generated.mp4",
            video_url="https://example.com/generated.mp4",
        )
        packager = Mock()
        packager.is_available.return_value = False
        image_handler = Mock()

        handler = LivePhotoHandler(provider, packager, image_handler)
        result = handler({"prompt": "dynamic selfie"})

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["fallback_kind"], "video")
        self.assertEqual(result["delivery_video_path"], "/tmp/generated.mp4")
        self.assertEqual(result["delivery_video_url"], "https://example.com/generated.mp4")
        self.assertEqual(result["cleanup_paths"], ["/tmp/generated.mp4"])
        self.assertIn("motion video only", result["warning"])
        image_handler.assert_not_called()


class TestLivePhotoPackager(unittest.TestCase):
    def test_package_creates_manifest_and_declares_cleanup_paths(self) -> None:
        created_outputs: list[str] = []

        def fake_runner(command: list[str], **kwargs: object) -> CompletedProcess[str]:
            if command[0] != "/usr/bin/makelive":
                output_path = command[-1]
                Path(output_path).write_bytes(b"placeholder")
                created_outputs.append(output_path)
            return CompletedProcess(command, 0, "", "")

        with tempfile.NamedTemporaryFile(prefix="analyst_live_video_", suffix=".mp4", delete=False) as tmp:
            tmp.write(b"video bytes")
            source_path = tmp.name

        with patch("analyst.tools._live_photo.platform.system", return_value="Darwin"):
            packager = LivePhotoPackager(
                config=LivePhotoPackagingConfig(
                    ffmpeg_binary="/usr/bin/ffmpeg",
                    makelive_binary="makelive",
                ),
                runner=fake_runner,
                which=lambda binary: f"/usr/bin/{binary}",
            )
            artifact = packager.package(GeneratedVideo(video_path=source_path))

        self.assertTrue(Path(artifact.live_photo_image_path).exists())
        self.assertTrue(Path(artifact.live_photo_video_path).exists())
        self.assertTrue(Path(artifact.manifest_path).exists())
        manifest = json.loads(Path(artifact.manifest_path).read_text(encoding="utf-8"))
        self.assertEqual(manifest["asset_id"], artifact.asset_id)
        self.assertEqual(manifest["delivery_video_path"], source_path)
        self.assertTrue(manifest["metadata_tagged"])
        self.assertEqual(manifest["packager"], "makelive")
        self.assertIn(source_path, artifact.cleanup_paths)

        for path in artifact.cleanup_paths:
            if os.path.exists(path):
                Path(path).unlink()


class TestLivePhotoToolAvailability(unittest.TestCase):
    def test_optional_builder_returns_none_when_not_configured(self) -> None:
        with patch("analyst.tools._live_photo.SeedDanceConfig.from_env_optional", return_value=None):
            self.assertIsNone(build_optional_live_photo_tool())

    def test_optional_builder_returns_tool_when_binaries_are_missing(self) -> None:
        with patch("analyst.tools._live_photo.resolve_ffmpeg_binary", return_value=""):
            tool = build_optional_live_photo_tool(
                config=SeedDanceConfig(
                    api_key="test-key",
                    base_url="https://seedance.example/api/v3",
                    model="seedance-test",
                ),
                which=lambda _: None,
                image_config=ImageGenConfig(
                    api_key="ark-key",
                    base_url="https://ark.example/api/v3",
                    model="image-model",
                ),
            )
            self.assertIsNotNone(tool)

    def test_optional_builder_returns_tool_off_macos(self) -> None:
        with patch("analyst.tools._live_photo.platform.system", return_value="Linux"):
            tool = build_optional_live_photo_tool(
                config=SeedDanceConfig(
                    api_key="test-key",
                    base_url="https://seedance.example/api/v3",
                    model="seedance-test",
                ),
                which=lambda binary: f"/usr/bin/{binary}",
                image_config=ImageGenConfig(
                    api_key="ark-key",
                    base_url="https://ark.example/api/v3",
                    model="image-model",
                ),
            )
            self.assertIsNotNone(tool)


class TestSalesChatMediaExtraction(unittest.TestCase):
    def test_extract_media_returns_video_item_for_live_photo_results(self) -> None:
        messages = [
            ConversationMessage(
                role="tool",
                tool_name="generate_live_photo",
                content=json.dumps(
                    {
                        "status": "ok",
                        "fallback_kind": "live_photo",
                        "asset_id": "asset-1",
                        "delivery_video_path": "/tmp/analyst_live_video.mp4",
                        "live_photo_image_path": "/tmp/analyst_live_cover.jpg",
                        "live_photo_video_path": "/tmp/analyst_live_photo.mov",
                        "live_photo_manifest_path": "/tmp/analyst_live_manifest.json",
                        "cleanup_paths": [
                            "/tmp/analyst_live_video.mp4",
                            "/tmp/analyst_live_cover.jpg",
                        ],
                    }
                ),
            ),
        ]

        media = _extract_media(messages)

        self.assertEqual(len(media), 1)
        self.assertEqual(media[0].kind, "video")
        self.assertEqual(media[0].url, "/tmp/analyst_live_video.mp4")
        self.assertEqual(media[0].cleanup_paths, ("/tmp/analyst_live_video.mp4", "/tmp/analyst_live_cover.jpg"))
        self.assertEqual(media[0].metadata["asset_id"], "asset-1")

    def test_extract_media_returns_video_item_for_motion_video_results(self) -> None:
        messages = [
            ConversationMessage(
                role="tool",
                tool_name="generate_live_photo",
                content=json.dumps(
                    {
                        "status": "ok",
                        "fallback_kind": "video",
                        "delivery_video_path": "/tmp/analyst_live_video.mp4",
                        "cleanup_paths": ["/tmp/analyst_live_video.mp4"],
                    }
                ),
            ),
        ]

        media = _extract_media(messages)

        self.assertEqual(len(media), 1)
        self.assertEqual(media[0].kind, "video")
        self.assertEqual(media[0].url, "/tmp/analyst_live_video.mp4")
        self.assertEqual(media[0].cleanup_paths, ("/tmp/analyst_live_video.mp4",))


def _json_response(payload: dict[str, object]) -> Mock:
    response = Mock()
    response.status_code = 200
    response.json.return_value = payload
    response.text = json.dumps(payload)
    return response


def _download_response(payload: bytes) -> Mock:
    response = Mock()
    response.status_code = 200
    response.content = payload
    return response


if __name__ == "__main__":
    unittest.main()
