from __future__ import annotations

import sys
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
            base_url="https://openrouter.example/api/v1",
            model="test-model",
        )

    def test_invalid_inline_data_returns_tool_error(self) -> None:
        response = Mock(status_code=200)
        response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "inline_data", "mime_type": "image/png", "data": "not-base64"},
                        ],
                    },
                },
            ],
        }
        session = Mock()
        session.post.return_value = response

        handler = ImageGenHandler(self.config, session=session)
        result = handler({"prompt": "generate a chart"})

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"], "No image found in model response")

    def test_invalid_json_response_returns_tool_error(self) -> None:
        response = Mock(status_code=200)
        response.json.side_effect = ValueError("bad json")
        session = Mock()
        session.post.return_value = response

        handler = ImageGenHandler(self.config, session=session)
        result = handler({"prompt": "generate a chart"})

        self.assertEqual(result, {"status": "error", "error": "Invalid API response"})


if __name__ == "__main__":
    unittest.main()
