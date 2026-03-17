"""Tests for the image decision layer (Phase 1).

Covers: hard blocks, explicit request overrides, soft recommendations,
visual scene extraction, image log storage CRUD, and counter queries.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst.delivery.image_decision import (
    DAILY_LIMITS,
    MIN_TURN_GAP,
    ImageDecision,
    detect_explicit_image_request,
    extract_visual_scene,
    should_generate_image,
    validate_scene_coherence,
)
from analyst.storage import SQLiteEngineStore


def _make_store() -> SQLiteEngineStore:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return SQLiteEngineStore(db_path=Path(tmp.name))


# ---------------------------------------------------------------------------
# Hard blocks
# ---------------------------------------------------------------------------

class TestStageBlock(unittest.TestCase):
    def test_stranger_always_blocked(self):
        decision = should_generate_image(
            reply_text="", relationship_stage="stranger",
            images_sent_today=0, turns_since_last_image=999,
            current_hour=12, user_text="",
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.block_reason, "stage_stranger")

    def test_stranger_blocked_even_with_explicit_request(self):
        decision = should_generate_image(
            reply_text="", relationship_stage="stranger",
            images_sent_today=0, turns_since_last_image=999,
            current_hour=12, user_text="发个自拍",
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.block_reason, "stage_stranger")


class TestDailyLimit(unittest.TestCase):
    def test_acquaintance_limit_1(self):
        decision = should_generate_image(
            reply_text="", relationship_stage="acquaintance",
            images_sent_today=1, turns_since_last_image=999,
            current_hour=12, user_text="",
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.block_reason, "daily_limit_reached")

    def test_familiar_limit_3(self):
        decision = should_generate_image(
            reply_text="", relationship_stage="familiar",
            images_sent_today=3, turns_since_last_image=999,
            current_hour=12, user_text="",
        )
        self.assertFalse(decision.allowed)

    def test_close_limit_5(self):
        decision = should_generate_image(
            reply_text="", relationship_stage="close",
            images_sent_today=5, turns_since_last_image=999,
            current_hour=12, user_text="",
        )
        self.assertFalse(decision.allowed)

    def test_under_limit_allowed(self):
        decision = should_generate_image(
            reply_text="", relationship_stage="close",
            images_sent_today=4, turns_since_last_image=999,
            current_hour=12, user_text="",
        )
        self.assertTrue(decision.allowed)

    def test_explicit_request_overrides_daily_limit(self):
        decision = should_generate_image(
            reply_text="", relationship_stage="acquaintance",
            images_sent_today=1, turns_since_last_image=999,
            current_hour=12, user_text="发个自拍",
        )
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.recommended)


class TestTurnGap(unittest.TestCase):
    def test_acquaintance_needs_5_turns(self):
        decision = should_generate_image(
            reply_text="", relationship_stage="acquaintance",
            images_sent_today=0, turns_since_last_image=4,
            current_hour=12, user_text="",
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.block_reason, "turn_gap_too_small")

    def test_acquaintance_at_5_turns_allowed(self):
        decision = should_generate_image(
            reply_text="", relationship_stage="acquaintance",
            images_sent_today=0, turns_since_last_image=5,
            current_hour=12, user_text="",
        )
        self.assertTrue(decision.allowed)

    def test_familiar_needs_3_turns(self):
        decision = should_generate_image(
            reply_text="", relationship_stage="familiar",
            images_sent_today=0, turns_since_last_image=2,
            current_hour=12, user_text="",
        )
        self.assertFalse(decision.allowed)

    def test_explicit_request_overrides_turn_gap(self):
        decision = should_generate_image(
            reply_text="", relationship_stage="acquaintance",
            images_sent_today=0, turns_since_last_image=1,
            current_hour=12, user_text="拍张照片",
        )
        self.assertTrue(decision.allowed)


class TestLateNight(unittest.TestCase):
    def test_blocked_at_23(self):
        decision = should_generate_image(
            reply_text="", relationship_stage="close",
            images_sent_today=0, turns_since_last_image=999,
            current_hour=23, user_text="",
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.block_reason, "late_night")

    def test_blocked_at_3am(self):
        decision = should_generate_image(
            reply_text="", relationship_stage="close",
            images_sent_today=0, turns_since_last_image=999,
            current_hour=3, user_text="",
        )
        self.assertFalse(decision.allowed)

    def test_allowed_at_7am(self):
        decision = should_generate_image(
            reply_text="", relationship_stage="close",
            images_sent_today=0, turns_since_last_image=999,
            current_hour=7, user_text="",
        )
        self.assertTrue(decision.allowed)

    def test_allowed_at_22(self):
        decision = should_generate_image(
            reply_text="", relationship_stage="close",
            images_sent_today=0, turns_since_last_image=999,
            current_hour=22, user_text="",
        )
        self.assertTrue(decision.allowed)

    def test_explicit_overrides_late_night(self):
        decision = should_generate_image(
            reply_text="", relationship_stage="close",
            images_sent_today=0, turns_since_last_image=999,
            current_hour=2, user_text="send me a selfie",
        )
        self.assertTrue(decision.allowed)


class TestEmotionalDistress(unittest.TestCase):
    def test_emotional_topic_high_engagement_blocks(self):
        decision = should_generate_image(
            reply_text="", relationship_stage="close",
            images_sent_today=0, turns_since_last_image=999,
            current_hour=12, user_text="",
            active_topic="mood / emotional", topic_engagement=0.8,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.block_reason, "emotional_distress")

    def test_emotional_topic_low_engagement_allowed(self):
        decision = should_generate_image(
            reply_text="", relationship_stage="close",
            images_sent_today=0, turns_since_last_image=999,
            current_hour=12, user_text="",
            active_topic="mood / emotional", topic_engagement=0.3,
        )
        self.assertTrue(decision.allowed)

    def test_high_stress_blocks(self):
        decision = should_generate_image(
            reply_text="", relationship_stage="close",
            images_sent_today=0, turns_since_last_image=999,
            current_hour=12, user_text="",
            stress_level="high",
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.block_reason, "user_stress_high")

    def test_critical_stress_blocks(self):
        decision = should_generate_image(
            reply_text="", relationship_stage="close",
            images_sent_today=0, turns_since_last_image=999,
            current_hour=12, user_text="",
            stress_level="critical",
        )
        self.assertFalse(decision.allowed)

    def test_explicit_request_overrides_stress(self):
        decision = should_generate_image(
            reply_text="", relationship_stage="close",
            images_sent_today=0, turns_since_last_image=999,
            current_hour=12, user_text="让我看看",
            stress_level="high",
        )
        self.assertTrue(decision.allowed)


class TestProactiveFrequencyCaps(unittest.TestCase):
    def test_proactive_daily_limit(self):
        decision = should_generate_image(
            reply_text="", relationship_stage="close",
            images_sent_today=0, turns_since_last_image=999,
            current_hour=12, is_proactive=True, outreach_kind="morning",
            user_text="", proactive_images_today=1,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.block_reason, "proactive_daily_limit")

    def test_warmup_5day_limit(self):
        decision = should_generate_image(
            reply_text="", relationship_stage="close",
            images_sent_today=0, turns_since_last_image=999,
            current_hour=12, is_proactive=True, outreach_kind="warm_up_share",
            user_text="", warmup_images_last_5_days=1,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.block_reason, "warmup_5day_limit")


# ---------------------------------------------------------------------------
# Explicit request detection
# ---------------------------------------------------------------------------

class TestExplicitRequestDetection(unittest.TestCase):
    def test_chinese_selfie_request(self):
        self.assertTrue(detect_explicit_image_request("发个自拍"))
        self.assertTrue(detect_explicit_image_request("来个自拍呗"))
        self.assertTrue(detect_explicit_image_request("拍张照片给我看"))
        self.assertTrue(detect_explicit_image_request("让我看看你"))
        self.assertTrue(detect_explicit_image_request("你长什么样"))
        self.assertTrue(detect_explicit_image_request("穿了什么呀"))

    def test_english_selfie_request(self):
        self.assertTrue(detect_explicit_image_request("send me a photo"))
        self.assertTrue(detect_explicit_image_request("Send me a selfie"))
        self.assertTrue(detect_explicit_image_request("take a photo for me"))
        self.assertTrue(detect_explicit_image_request("your photo please"))

    def test_no_request(self):
        self.assertFalse(detect_explicit_image_request("今天天气不错"))
        self.assertFalse(detect_explicit_image_request("hello"))
        self.assertFalse(detect_explicit_image_request("你好"))
        self.assertFalse(detect_explicit_image_request(""))

    def test_partial_match(self):
        self.assertTrue(detect_explicit_image_request("可以发张照片吗"))
        self.assertTrue(detect_explicit_image_request("send me a pic of you"))


# ---------------------------------------------------------------------------
# Visual scene extraction
# ---------------------------------------------------------------------------

class TestVisualSceneExtraction(unittest.TestCase):
    def test_coffee(self):
        self.assertEqual(extract_visual_scene("去喝咖啡了"), "coffee_table_pov")
        self.assertEqual(extract_visual_scene("having coffee"), "coffee_table_pov")

    def test_food(self):
        self.assertEqual(extract_visual_scene("午饭吃什么"), "lunch_table_food")
        self.assertEqual(extract_visual_scene("having lunch"), "lunch_table_food")

    def test_rain(self):
        self.assertEqual(extract_visual_scene("外面下雨了"), "home_window_view")
        self.assertEqual(extract_visual_scene("rainy day today"), "home_window_view")

    def test_walk(self):
        self.assertEqual(extract_visual_scene("出去散步"), "street_walk_view")

    def test_desk(self):
        self.assertEqual(extract_visual_scene("在办公呢"), "desk_midday_pov")

    def test_no_match(self):
        self.assertIsNone(extract_visual_scene("你好"))
        self.assertIsNone(extract_visual_scene(""))


# ---------------------------------------------------------------------------
# Soft recommendations
# ---------------------------------------------------------------------------

class TestSoftRecommendations(unittest.TestCase):
    def test_visual_scene_in_reply_recommends_back_camera(self):
        decision = should_generate_image(
            reply_text="我刚去喝咖啡了", relationship_stage="familiar",
            images_sent_today=0, turns_since_last_image=999,
            current_hour=14, user_text="",
        )
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.recommended)
        self.assertEqual(decision.mode, "back_camera")
        self.assertEqual(decision.scene_hint, "coffee_table_pov")

    def test_no_visual_scene_not_recommended(self):
        decision = should_generate_image(
            reply_text="今天过得不错", relationship_stage="familiar",
            images_sent_today=0, turns_since_last_image=999,
            current_hour=14, user_text="",
        )
        self.assertTrue(decision.allowed)
        self.assertFalse(decision.recommended)

    def test_proactive_warm_up_share_recommends(self):
        decision = should_generate_image(
            reply_text="", relationship_stage="familiar",
            images_sent_today=0, turns_since_last_image=999,
            current_hour=14, is_proactive=True, outreach_kind="warm_up_share",
            user_text="",
        )
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.recommended)
        self.assertEqual(decision.mode, "back_camera")

    def test_proactive_stage_milestone_recommends_selfie(self):
        decision = should_generate_image(
            reply_text="", relationship_stage="familiar",
            images_sent_today=0, turns_since_last_image=999,
            current_hour=14, is_proactive=True, outreach_kind="stage_milestone",
            user_text="",
        )
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.recommended)
        self.assertEqual(decision.mode, "selfie")


# ---------------------------------------------------------------------------
# Scene coherence (Phase 3)
# ---------------------------------------------------------------------------

class TestSceneCoherence(unittest.TestCase):
    def test_matching_library(self):
        coherent, override = validate_scene_coherence(
            "我在图书馆看书", "library study desk with books", "back_camera"
        )
        self.assertTrue(coherent)
        self.assertIsNone(override)

    def test_conflict_library_vs_cafe(self):
        coherent, override = validate_scene_coherence(
            "我在图书馆看书", "coffee shop table with latte", "back_camera"
        )
        self.assertFalse(coherent)
        self.assertEqual(override, "library_desk")

    def test_no_location_in_reply_allows_freestyle(self):
        coherent, override = validate_scene_coherence(
            "今天心情不错", "coffee shop table", "back_camera"
        )
        self.assertTrue(coherent)
        self.assertIsNone(override)

    def test_matching_home(self):
        coherent, override = validate_scene_coherence(
            "在家里窝着", "home near a window", "back_camera"
        )
        self.assertTrue(coherent)
        self.assertIsNone(override)

    def test_conflict_home_vs_office(self):
        coherent, override = validate_scene_coherence(
            "在家里看电影", "office desk with laptop", "back_camera"
        )
        self.assertFalse(coherent)
        self.assertEqual(override, "home_window_view")


# ---------------------------------------------------------------------------
# Image log storage CRUD
# ---------------------------------------------------------------------------

class TestImageLogStorage(unittest.TestCase):
    def test_log_and_count(self):
        store = _make_store()
        store.log_companion_image(
            client_id="u1", channel="telegram:123", thread_id="main",
            mode="selfie", trigger_type="reactive",
            relationship_stage="familiar",
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        count = store.count_images_sent_today(client_id="u1")
        self.assertEqual(count, 1)

    def test_blocked_images_not_counted(self):
        store = _make_store()
        store.log_companion_image(
            client_id="u1", channel="telegram:123", thread_id="main",
            mode="selfie", trigger_type="reactive",
            relationship_stage="familiar",
            generated_at=datetime.now(timezone.utc).isoformat(),
            blocked=True, block_reason="daily_limit_reached",
        )
        count = store.count_images_sent_today(client_id="u1")
        self.assertEqual(count, 0)

    def test_proactive_count(self):
        store = _make_store()
        store.log_companion_image(
            client_id="u1", channel="telegram:123", thread_id="main",
            mode="back_camera", trigger_type="proactive", outreach_kind="warm_up_share",
            relationship_stage="close",
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        store.log_companion_image(
            client_id="u1", channel="telegram:123", thread_id="main",
            mode="selfie", trigger_type="reactive",
            relationship_stage="close",
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        proactive = store.count_proactive_images_today(client_id="u1")
        self.assertEqual(proactive, 1)
        total = store.count_images_sent_today(client_id="u1")
        self.assertEqual(total, 2)

    def test_warmup_5day_count(self):
        store = _make_store()
        store.log_companion_image(
            client_id="u1", channel="telegram:123", thread_id="main",
            mode="back_camera", trigger_type="proactive", outreach_kind="warm_up_share",
            relationship_stage="close",
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        count = store.count_warmup_images_last_5_days(client_id="u1")
        self.assertEqual(count, 1)

    def test_turns_since_last_image_no_images(self):
        store = _make_store()
        turns = store.get_turns_since_last_image(
            client_id="u1", channel="telegram:123", thread_id="main",
        )
        self.assertEqual(turns, 999)

    def test_turns_since_last_image_with_messages(self):
        store = _make_store()
        # Log an image with a timestamp well in the past
        store.log_companion_image(
            client_id="u1", channel="telegram:123", thread_id="main",
            mode="selfie", trigger_type="reactive",
            relationship_stage="close",
            generated_at="2020-01-01T00:00:00+00:00",
        )
        # Add messages after the image (created_at = utc_now, which is after 2020)
        store.append_conversation_message(
            client_id="u1", channel="telegram:123", thread_id="main",
            role="user", content="hello",
        )
        store.append_conversation_message(
            client_id="u1", channel="telegram:123", thread_id="main",
            role="assistant", content="hi",
        )
        turns = store.get_turns_since_last_image(
            client_id="u1", channel="telegram:123", thread_id="main",
        )
        self.assertEqual(turns, 2)

    def test_log_returns_record(self):
        store = _make_store()
        record = store.log_companion_image(
            client_id="u1", channel="telegram:123", thread_id="main",
            mode="selfie", scene_key="coffee_shop",
            trigger_type="explicit", outreach_kind="",
            relationship_stage="familiar",
            generated_at="2026-03-17T12:00:00+00:00",
        )
        self.assertEqual(record.client_id, "u1")
        self.assertEqual(record.mode, "selfie")
        self.assertEqual(record.scene_key, "coffee_shop")
        self.assertEqual(record.trigger_type, "explicit")
        self.assertFalse(record.blocked)
        self.assertGreater(record.image_log_id, 0)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    def test_explicit_back_camera_detection(self):
        """Explicit request with back_camera keywords should infer back_camera mode."""
        decision = should_generate_image(
            reply_text="", relationship_stage="familiar",
            images_sent_today=0, turns_since_last_image=999,
            current_hour=12, user_text="发张照片看看你吃什么",
        )
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.recommended)
        self.assertEqual(decision.mode, "back_camera")

    def test_explicit_selfie_detection(self):
        """Explicit selfie request without back_camera keywords defaults to selfie."""
        decision = should_generate_image(
            reply_text="", relationship_stage="familiar",
            images_sent_today=0, turns_since_last_image=999,
            current_hour=12, user_text="发个自拍",
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.mode, "selfie")

    def test_all_soft_blocks_combined(self):
        """Multiple soft blocks active — first hard block wins."""
        decision = should_generate_image(
            reply_text="", relationship_stage="acquaintance",
            images_sent_today=1, turns_since_last_image=1,
            current_hour=23, user_text="",
            stress_level="high",
        )
        self.assertFalse(decision.allowed)
        # First block hit is daily_limit_reached
        self.assertEqual(decision.block_reason, "daily_limit_reached")

    def test_limits_dict_completeness(self):
        """All known stages have entries in DAILY_LIMITS and MIN_TURN_GAP."""
        for stage in ("stranger", "acquaintance", "familiar", "close"):
            self.assertIn(stage, DAILY_LIMITS)
            self.assertIn(stage, MIN_TURN_GAP)


if __name__ == "__main__":
    unittest.main()
