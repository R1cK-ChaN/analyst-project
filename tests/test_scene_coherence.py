"""Tests for scene coherence validation (Phase 3).

Covers: matching scenarios, conflicting scenarios, no-match scenarios,
and new scene preset availability.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from analyst.delivery.image_decision import validate_scene_coherence
from analyst.tools._selfie_persona import (
    _SCENE_CATALOG,
    _BACK_CAMERA_SCENE_CATALOG,
)


# ---------------------------------------------------------------------------
# Scene coherence: matching
# ---------------------------------------------------------------------------

class TestSceneCoherenceMatching(unittest.TestCase):
    def test_library_text_library_scene(self):
        coherent, override = validate_scene_coherence(
            "我在图书馆复习", "library study desk with books", "back_camera",
        )
        self.assertTrue(coherent)
        self.assertIsNone(override)

    def test_cafe_text_cafe_scene(self):
        coherent, override = validate_scene_coherence(
            "在咖啡店坐着", "coffee shop table with latte", "back_camera",
        )
        self.assertTrue(coherent)
        self.assertIsNone(override)

    def test_home_text_home_scene(self):
        coherent, override = validate_scene_coherence(
            "在家里躺着", "home near a window in the evening", "back_camera",
        )
        self.assertTrue(coherent)
        self.assertIsNone(override)

    def test_office_text_office_scene(self):
        coherent, override = validate_scene_coherence(
            "在办公室加班", "office desk with laptop and coffee", "back_camera",
        )
        self.assertTrue(coherent)
        self.assertIsNone(override)

    def test_street_text_street_scene(self):
        coherent, override = validate_scene_coherence(
            "在街上散步", "walking on a street with city lights", "back_camera",
        )
        self.assertTrue(coherent)
        self.assertIsNone(override)


# ---------------------------------------------------------------------------
# Scene coherence: conflicts
# ---------------------------------------------------------------------------

class TestSceneCoherenceConflict(unittest.TestCase):
    def test_library_text_cafe_scene_overrides(self):
        coherent, override = validate_scene_coherence(
            "我在图书馆看书", "café table with latte and laptop", "back_camera",
        )
        self.assertFalse(coherent)
        self.assertEqual(override, "library_desk")

    def test_home_text_office_scene_overrides(self):
        coherent, override = validate_scene_coherence(
            "在家里看电影", "office desk with scattered papers", "back_camera",
        )
        self.assertFalse(coherent)
        self.assertEqual(override, "home_window_view")

    def test_park_text_subway_scene_overrides(self):
        coherent, override = validate_scene_coherence(
            "在公园晒太阳", "subway train interior with commuters", "back_camera",
        )
        self.assertFalse(coherent)
        self.assertEqual(override, "park_bench")

    def test_rain_text_office_scene_overrides(self):
        coherent, override = validate_scene_coherence(
            "外面下雨了好大", "office desk at noon", "back_camera",
        )
        self.assertFalse(coherent)
        self.assertEqual(override, "rainy_window")


# ---------------------------------------------------------------------------
# Scene coherence: no-match
# ---------------------------------------------------------------------------

class TestSceneCoherenceNoMatch(unittest.TestCase):
    def test_no_location_in_reply(self):
        coherent, override = validate_scene_coherence(
            "今天心情还不错", "coffee shop table", "back_camera",
        )
        self.assertTrue(coherent)
        self.assertIsNone(override)

    def test_empty_reply(self):
        coherent, override = validate_scene_coherence(
            "", "home window", "back_camera",
        )
        self.assertTrue(coherent)
        self.assertIsNone(override)

    def test_generic_text_no_location(self):
        coherent, override = validate_scene_coherence(
            "lol that's funny", "desk with books", "selfie",
        )
        self.assertTrue(coherent)
        self.assertIsNone(override)

    def test_no_location_in_scene_prompt(self):
        coherent, override = validate_scene_coherence(
            "在办公室开会", "a person smiling at camera", "selfie",
        )
        # Reply has location (office) but scene prompt has none — allow
        self.assertTrue(coherent)
        self.assertIsNone(override)


# ---------------------------------------------------------------------------
# New scene presets exist
# ---------------------------------------------------------------------------

class TestNewScenePresets(unittest.TestCase):
    def test_new_selfie_scenes_exist(self):
        for key in ("sleepy_morning", "bundled_up", "study_tired"):
            self.assertIn(key, _SCENE_CATALOG, f"Missing selfie scene: {key}")
            scene = _SCENE_CATALOG[key]
            self.assertTrue(scene.scene_prompt, f"Empty scene_prompt for {key}")
            self.assertTrue(scene.motion_prompt, f"Empty motion_prompt for {key}")

    def test_new_back_camera_scenes_exist(self):
        for key in ("library_desk", "rainy_window", "night_desk", "grocery_fruit", "park_bench", "subway_commute"):
            self.assertIn(key, _BACK_CAMERA_SCENE_CATALOG, f"Missing back_camera scene: {key}")
            scene = _BACK_CAMERA_SCENE_CATALOG[key]
            self.assertTrue(scene.scene_prompt, f"Empty scene_prompt for {key}")

    def test_original_selfie_scenes_still_exist(self):
        for key in ("coffee_shop", "lazy_sunday_home", "night_walk", "gym_mirror",
                     "airport_waiting", "bedroom_late_night", "rainy_day_window", "weekend_street"):
            self.assertIn(key, _SCENE_CATALOG, f"Missing original selfie scene: {key}")

    def test_original_back_camera_scenes_still_exist(self):
        for key in ("lunch_table_food", "coffee_table_pov", "desk_midday_pov",
                     "home_window_view", "street_walk_view"):
            self.assertIn(key, _BACK_CAMERA_SCENE_CATALOG, f"Missing original back_camera scene: {key}")


if __name__ == "__main__":
    unittest.main()
