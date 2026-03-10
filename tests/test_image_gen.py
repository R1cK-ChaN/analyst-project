from __future__ import annotations

import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst.tools._image_gen import (
    GeneratedImage,
    ImageGenConfig,
    ImageGenHandler,
    ImageGenerationError,
    SeedreamImageClient,
)
from analyst.tools._request_context import RequestImageInput, bind_request_image


class TestImageGenHandler(unittest.TestCase):
    def setUp(self) -> None:
        self.config = ImageGenConfig(
            api_key="test-key",
            base_url="https://ark.example/api/v3",
            model="doubao-seedream-5-0-260128",
        )

    def test_url_response_returns_image_url(self) -> None:
        response = Mock(status_code=200)
        response.json.return_value = {
            "data": [
                {
                    "url": "https://example.com/generated.jpeg",
                    "size": "2048x2048",
                },
            ],
        }
        session = Mock()
        session.post.return_value = response

        handler = ImageGenHandler(self.config, session=session)
        result = handler({"prompt": "generate a chart"})

        self.assertEqual(
            result,
            {
                "status": "ok",
                "image_url": "https://example.com/generated.jpeg",
                "prompt_used": "generate a chart",
            },
        )

    def test_base64_response_is_saved_to_temp_file(self) -> None:
        response = Mock(status_code=200)
        response.json.return_value = {
            "data": [
                {
                    "b64_json": base64.b64encode(b"fake image bytes").decode("ascii"),
                },
            ],
        }
        session = Mock()
        session.post.return_value = response

        handler = ImageGenHandler(self.config, session=session)
        result = handler({"prompt": "generate a chart"})

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["image_path"].startswith(tempfile.gettempdir()))
        self.assertEqual(Path(result["image_path"]).read_bytes(), b"fake image bytes")
        Path(result["image_path"]).unlink()

    def test_invalid_json_response_returns_tool_error(self) -> None:
        response = Mock(status_code=200)
        response.json.side_effect = ValueError("bad json")
        session = Mock()
        session.post.return_value = response

        handler = ImageGenHandler(self.config, session=session)
        result = handler({"prompt": "generate a chart"})

        self.assertEqual(result, {"status": "error", "error": "Invalid API response"})

    def test_invalid_base64_response_returns_tool_error(self) -> None:
        response = Mock(status_code=200)
        response.json.return_value = {"data": [{"b64_json": "not-base64"}]}
        session = Mock()
        session.post.return_value = response

        handler = ImageGenHandler(self.config, session=session)
        result = handler({"prompt": "generate a chart"})

        self.assertEqual(result, {"status": "error", "error": "No image found in model response"})

    def test_selfie_mode_routes_through_selfie_service(self) -> None:
        image_client = Mock()
        selfie_service = Mock()
        selfie_service.is_selfie_request.return_value = True
        selfie_service.generate_selfie.return_value = Mock(
            image_path="/tmp/persona.jpg",
            prompt_used="assembled prompt",
            scene_key="trading_desk",
            scene_prompt="taking a selfie at a trading desk",
            negative_prompt="different person",
        )

        handler = ImageGenHandler(
            self.config,
            image_client=image_client,
            selfie_service=selfie_service,
        )
        result = handler({"mode": "selfie", "scene_key": "trading_desk"})

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["image_path"], "/tmp/persona.jpg")
        self.assertEqual(result["mode"], "selfie")
        self.assertEqual(result["scene_key"], "trading_desk")
        selfie_service.generate_selfie.assert_called_once()

    def test_selfie_timeout_falls_back_to_generic_image(self) -> None:
        image_client = Mock()
        image_client.generate_image.return_value = GeneratedImage(image_url="https://example.com/fallback.jpg")
        selfie_service = Mock()
        selfie_service.is_selfie_request.return_value = True
        selfie_service.generate_selfie.side_effect = ImageGenerationError("timed out", retryable=True)
        selfie_service.build_prompt_draft.return_value = Mock(
            fallback_prompt="realistic smartphone photo of coffee on a cafe table",
            negative_prompt="different person",
            scene_key="coffee_shop",
            scene_prompt="holding a coffee cup near the camera",
        )

        handler = ImageGenHandler(
            self.config,
            image_client=image_client,
            selfie_service=selfie_service,
        )
        result = handler({"mode": "selfie", "scene_key": "coffee_shop"})

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["fallback_kind"], "generic_image")
        self.assertEqual(result["mode"], "selfie")
        self.assertEqual(result["scene_key"], "coffee_shop")
        image_client.generate_image.assert_called_once_with(
            prompt="realistic smartphone photo of coffee on a cafe table",
            negative_prompt="different person",
        )

    def test_generic_mode_can_use_attached_image_context(self) -> None:
        image_client = Mock()
        image_client.generate_image.return_value = Mock(
            image_path="",
            image_url="https://example.com/variation.jpg",
        )
        selfie_service = Mock()
        selfie_service.is_selfie_request.return_value = False
        handler = ImageGenHandler(
            self.config,
            image_client=image_client,
            selfie_service=selfie_service,
        )

        with bind_request_image(
            RequestImageInput(
                data_uri="data:image/jpeg;base64,abc",
                mime_type="image/jpeg",
                filename="user.jpg",
            )
        ):
            result = handler({"prompt": "make it cinematic", "use_attached_image": True})

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["used_attached_image"])
        image_client.generate_image.assert_called_once_with(
            prompt="make it cinematic",
            image_input="data:image/jpeg;base64,abc",
        )


class TestSeedreamImageClient(unittest.TestCase):
    def test_includes_watermark_flag_in_request_payload(self) -> None:
        response = Mock(status_code=200)
        response.json.return_value = {"data": [{"url": "https://example.com/generated.jpeg"}]}
        session = Mock()
        session.post.return_value = response
        client = SeedreamImageClient(
            ImageGenConfig(
                api_key="test-key",
                base_url="https://ark.example/api/v3",
                model="doubao-seedream-5-0-260128",
                watermark=False,
            ),
            session=session,
        )

        client.generate_image(prompt="generate a chart")

        payload = json.loads(session.post.call_args.kwargs["data"])
        self.assertIs(payload["watermark"], False)

    def test_retries_transient_timeout_before_success(self) -> None:
        response = Mock(status_code=200)
        response.json.return_value = {"data": [{"url": "https://example.com/generated.jpeg"}]}
        session = Mock()
        session.post.side_effect = [
            requests.ReadTimeout("timed out"),
            response,
        ]
        client = SeedreamImageClient(
            ImageGenConfig(
                api_key="test-key",
                base_url="https://ark.example/api/v3",
                model="doubao-seedream-5-0-260128",
                max_retries=1,
            ),
            session=session,
            sleep_fn=lambda _: None,
        )

        result = client.generate_image(prompt="generate a chart")

        self.assertEqual(result.image_url, "https://example.com/generated.jpeg")
        self.assertEqual(session.post.call_count, 2)


if __name__ == "__main__":
    unittest.main()
