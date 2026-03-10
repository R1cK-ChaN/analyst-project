from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst.tools._image_gen import GeneratedImage
from analyst.tools._selfie_persona import SelfiePromptConfig, SelfiePromptService


class FakeImageClient:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self.calls: list[dict[str, str]] = []
        self.failures_before_success = 0

    def generate_image(self, *, prompt: str, negative_prompt: str = "", image_input: str = "") -> GeneratedImage:
        if self.failures_before_success > 0:
            self.failures_before_success -= 1
            raise RuntimeError("temporary image generation failure")
        index = len(self.calls) + 1
        source_path = self._root / f"source_{index}.jpg"
        Image.new("RGB", (64, 64), color=(index * 20 % 255, 80, 120)).save(source_path, format="JPEG")
        self.calls.append(
            {
                "prompt": prompt,
                "negative_prompt": negative_prompt,
                "image_input": image_input,
            }
        )
        return GeneratedImage(image_path=str(source_path))

    def materialize_image(self, generated: GeneratedImage, target_path: Path) -> str:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(generated.image_path, target_path)
        return str(target_path)


class TestSelfiePromptService(unittest.TestCase):
    def test_generate_selfie_bootstraps_state_and_updates_latest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            service = SelfiePromptService(
                SelfiePromptConfig(
                    media_root=root / "persona",
                    bootstrap_count=4,
                )
            )
            client = FakeImageClient(root / "source")

            result = service.generate_selfie(
                {
                    "mode": "selfie",
                    "scene_key": "coffee_shop",
                    "scene_prompt": "wearing a dark blazer",
                },
                client,
            )

            state_path = root / "persona" / "persona_selfie_state.json"
            self.assertTrue(state_path.exists())
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(len(state["bootstrap_paths"]), 4)
            self.assertEqual(state["character_anchor_path"], state["bootstrap_paths"][0])
            self.assertEqual(state["latest_selfie_path"], result.image_path)
            self.assertEqual(state["character_dna"][0], "young Chinese male")
            self.assertEqual(state["camera_style"][0], "phone selfie")
            self.assertEqual(state["quality_modifiers"][0], "photorealistic")
            self.assertEqual(state["negative_prompt"][0], "old man")
            self.assertEqual(state["last_scene_key"], "coffee_shop")
            self.assertIn("holding a coffee cup", state["last_scene_prompt"])
            self.assertIn("young Chinese male", state["last_prompt_used"])
            self.assertEqual(len(client.calls), 5)
            self.assertEqual(client.calls[0]["image_input"], "")
            self.assertTrue(client.calls[-1]["image_input"].startswith("data:image/"))
            self.assertIn("different person", client.calls[-1]["negative_prompt"])
            self.assertIn("young Chinese male", result.prompt_used)
            self.assertIn("phone selfie", result.prompt_used)
            self.assertIn("holding a coffee cup", result.prompt_used)
            self.assertIn("photorealistic", result.prompt_used)
            self.assertEqual(result.scene_key, "coffee_shop")
            self.assertIn("wearing a dark blazer", result.scene_prompt)
            self.assertIn("lifting a coffee cup", result.motion_prompt)

    def test_is_selfie_request_detects_mode_or_scene_fields(self) -> None:
        service = SelfiePromptService(
            SelfiePromptConfig(media_root=Path(tempfile.gettempdir()) / "persona-test")
        )

        self.assertTrue(service.is_selfie_request({"mode": "selfie"}))
        self.assertTrue(service.is_selfie_request({"scene_key": "trading_desk"}))
        self.assertTrue(service.is_selfie_request({"scene_prompt": "coffee shop daylight"}))
        self.assertFalse(service.is_selfie_request({"prompt": "please send a selfie"}))
        self.assertFalse(service.is_selfie_request({"prompt": "draw a market chart"}))

    def test_bootstrap_retries_transient_failures_and_keeps_first_two_successes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            service = SelfiePromptService(
                SelfiePromptConfig(
                    media_root=root / "persona",
                    bootstrap_count=3,
                )
            )
            client = FakeImageClient(root / "source")
            client.failures_before_success = 1

            result = service.generate_selfie({"mode": "selfie", "scene_prompt": "standing by a window"}, client)

            state = json.loads((root / "persona" / "persona_selfie_state.json").read_text(encoding="utf-8"))
            self.assertEqual(len(state["bootstrap_paths"]), 3)
            self.assertEqual(state["character_anchor_path"], state["bootstrap_paths"][0])
            self.assertNotEqual(state["character_anchor_path"], state["latest_selfie_path"])
            self.assertEqual(state["latest_selfie_path"], result.image_path)
            self.assertEqual(len(client.calls), 4)


if __name__ == "__main__":
    unittest.main()
