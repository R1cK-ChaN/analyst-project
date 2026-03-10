from __future__ import annotations

import base64
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst.tools._image_gen import ImageGenConfig, ImageGenHandler


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


if __name__ == "__main__":
    unittest.main()
