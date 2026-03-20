from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from analyst.memory.relationship import (
    apply_tendency_damping,
    _get_dominant_tendency,
    _get_primary_nudge_target,
    compute_relationship_update,
    _DAMPING_FACTOR,
    _DAMPING_CONSECUTIVE_TO_CONFIRM,
    _DAMPING_DOMINANT_THRESHOLD,
    _TENDENCY_NUDGE_AMOUNT,
)
from analyst.memory.profile import RelationshipSignalUpdate
from analyst.storage.sqlite_records import CompanionRelationshipStateRecord
from analyst.memory.service import _render_companion_profile
from analyst.storage.sqlite_records import ClientProfileRecord


def _make_rel(**overrides) -> CompanionRelationshipStateRecord:
    defaults = dict(
        client_id="u1",
        intimacy_level=0.5,
        relationship_stage="familiar",
        tendency_friend=0.45,
        tendency_romantic=0.15,
        tendency_confidant=0.25,
        tendency_mentor=0.15,
        streak_days=5,
        total_turns=20,
        avg_session_turns=3.0,
        mood_history=[],
        nicknames=[],
        previous_stage="",
        last_interaction_date="2026-03-17",
        last_stage_transition_at="",
        created_at="",
        updated_at="",
        outreach_paused=False,
        outreach_paused_at="",
        peak_intimacy_level=0.5,
        tendency_damping_json="{}",
    )
    defaults.update(overrides)
    return CompanionRelationshipStateRecord(**defaults)


def _make_profile(**overrides) -> ClientProfileRecord:
    defaults = dict(
        client_id="u1",
        preferred_language="zh",
        watchlist_topics=[],
        response_style="",
        risk_appetite="",
        investment_horizon="",
        institution_type="",
        risk_preference="",
        asset_focus=[],
        market_focus=[],
        expertise_level="",
        activity="",
        current_mood="",
        emotional_trend="",
        stress_level="",
        confidence="",
        notes="",
        personal_facts=[],
        last_active_at="",
        total_interactions=10,
        updated_at="",
        timezone_name="Asia/Shanghai",
    )
    defaults.update(overrides)
    return ClientProfileRecord(**defaults)


class TestGetDominantTendency(unittest.TestCase):
    def test_clear_dominant(self):
        name, ratio = _get_dominant_tendency({"friend": 0.5, "romantic": 0.2, "confidant": 0.2, "mentor": 0.1})
        self.assertEqual(name, "friend")
        self.assertAlmostEqual(ratio, 0.5)

    def test_empty(self):
        name, ratio = _get_dominant_tendency({})
        self.assertEqual(name, "friend")

    def test_equal(self):
        name, ratio = _get_dominant_tendency({"friend": 0.25, "romantic": 0.25, "confidant": 0.25, "mentor": 0.25})
        self.assertIn(name, ["friend", "romantic", "confidant", "mentor"])
        self.assertAlmostEqual(ratio, 0.25)


class TestApplyTendencyDamping(unittest.TestCase):
    def test_aligned_nudge_full_amount(self):
        """Nudge aligned with dominant should return full amount."""
        tendencies = {"friend": 0.45, "romantic": 0.15, "confidant": 0.25, "mentor": 0.15}
        amount, state = apply_tendency_damping(tendencies, "friend", 0.02, {})
        self.assertAlmostEqual(amount, 0.02)
        self.assertEqual(state.get("spike_consecutive", 0), 0)

    def test_opposing_nudge_halved(self):
        """Nudge opposing strong dominant should be halved."""
        tendencies = {"friend": 0.45, "romantic": 0.15, "confidant": 0.25, "mentor": 0.15}
        amount, state = apply_tendency_damping(tendencies, "romantic", 0.02, {})
        self.assertAlmostEqual(amount, 0.02 * _DAMPING_FACTOR)
        self.assertEqual(state["spike_target"], "romantic")
        self.assertEqual(state["spike_consecutive"], 1)

    def test_weak_dominant_no_damping(self):
        """If no strong dominant (all ~0.25), nudge should not be damped."""
        tendencies = {"friend": 0.26, "romantic": 0.25, "confidant": 0.25, "mentor": 0.24}
        amount, state = apply_tendency_damping(tendencies, "romantic", 0.02, {})
        self.assertAlmostEqual(amount, 0.02)

    def test_consecutive_tracking(self):
        """Second opposing nudge should increment consecutive counter."""
        tendencies = {"friend": 0.45, "romantic": 0.15, "confidant": 0.25, "mentor": 0.15}
        _, state1 = apply_tendency_damping(tendencies, "romantic", 0.02, {})
        self.assertEqual(state1["spike_consecutive"], 1)

        amount2, state2 = apply_tendency_damping(tendencies, "romantic", 0.02, state1)
        self.assertAlmostEqual(amount2, 0.02 * _DAMPING_FACTOR)
        self.assertEqual(state2["spike_consecutive"], 2)

    def test_confirmed_shift_after_3(self):
        """After 3 consecutive opposing nudges, damping is removed and accumulated nudges applied."""
        tendencies = {"friend": 0.45, "romantic": 0.15, "confidant": 0.25, "mentor": 0.15}
        _, state1 = apply_tendency_damping(tendencies, "romantic", 0.02, {})
        _, state2 = apply_tendency_damping(tendencies, "romantic", 0.02, state1)
        amount3, state3 = apply_tendency_damping(tendencies, "romantic", 0.02, state2)

        # Should get full amount + accumulated dampened from turns 1 and 2
        accumulated_1_2 = 0.02 * (1 - _DAMPING_FACTOR) * 2  # two turns of accumulated
        expected = 0.02 + accumulated_1_2
        self.assertAlmostEqual(amount3, expected)
        self.assertEqual(state3["spike_consecutive"], 0)
        self.assertEqual(state3["spike_target"], "")

    def test_direction_change_resets(self):
        """Changing spike direction resets the counter."""
        tendencies = {"friend": 0.45, "romantic": 0.15, "confidant": 0.25, "mentor": 0.15}
        _, state1 = apply_tendency_damping(tendencies, "romantic", 0.02, {})
        self.assertEqual(state1["spike_target"], "romantic")

        amount2, state2 = apply_tendency_damping(tendencies, "mentor", 0.02, state1)
        self.assertEqual(state2["spike_target"], "mentor")
        self.assertEqual(state2["spike_consecutive"], 1)
        self.assertAlmostEqual(amount2, 0.02 * _DAMPING_FACTOR)

    def test_zero_nudge_passthrough(self):
        amount, state = apply_tendency_damping({"friend": 0.5}, "friend", 0.0, {})
        self.assertAlmostEqual(amount, 0.0)

    def test_empty_target_passthrough(self):
        amount, state = apply_tendency_damping({"friend": 0.5}, "", 0.02, {})
        self.assertAlmostEqual(amount, 0.02)


class TestDampingInComputeRelationshipUpdate(unittest.TestCase):
    def test_single_romantic_spike_damped(self):
        """A single romantic message from friend-dominant user should be damped."""
        rel = _make_rel(tendency_damping_json="{}")
        signal = RelationshipSignalUpdate(interaction_mode="flirting")
        now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        updates = compute_relationship_update(rel, signal=signal, now=now)
        # The romantic tendency should not have jumped as much as without damping
        self.assertIn("tendency_damping_json", updates)
        damping = json.loads(updates["tendency_damping_json"])
        self.assertEqual(damping.get("spike_target"), "romantic")
        self.assertEqual(damping.get("spike_consecutive"), 1)

    def test_three_romantic_signals_confirm(self):
        """Three consecutive romantic signals should confirm the shift."""
        rel = _make_rel(tendency_damping_json="{}")
        now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)

        # Turn 1
        signal1 = RelationshipSignalUpdate(interaction_mode="flirting")
        updates1 = compute_relationship_update(rel, signal=signal1, now=now)
        damping1 = json.loads(updates1["tendency_damping_json"])
        self.assertEqual(damping1["spike_consecutive"], 1)

        # Update rel for turn 2
        rel2 = _make_rel(tendency_damping_json=updates1["tendency_damping_json"])
        signal2 = RelationshipSignalUpdate(interaction_mode="flirting")
        updates2 = compute_relationship_update(rel2, signal=signal2, now=now)
        damping2 = json.loads(updates2["tendency_damping_json"])
        self.assertEqual(damping2["spike_consecutive"], 2)

        # Update rel for turn 3
        rel3 = _make_rel(tendency_damping_json=updates2["tendency_damping_json"])
        signal3 = RelationshipSignalUpdate(interaction_mode="flirting")
        updates3 = compute_relationship_update(rel3, signal=signal3, now=now)
        damping3 = json.loads(updates3["tendency_damping_json"])
        self.assertEqual(damping3["spike_consecutive"], 0)  # confirmed, reset


class TestPromptHintLifecycle(unittest.TestCase):
    def test_hint_present_during_ambiguous_window(self):
        """Hint should appear when spike_consecutive is 1 or 2."""
        rel = _make_rel(tendency_damping_json=json.dumps({
            "dominant_20": "friend", "dominant_ratio": 0.45,
            "spike_target": "romantic", "spike_consecutive": 1,
            "accumulated_dampened": {"romantic": 0.01},
        }))
        profile = _make_profile()
        lines = _render_companion_profile(profile, relationship=rel)
        text = "\n".join(lines)
        self.assertIn("风格和之前不太一样", text)

    def test_hint_absent_after_confirmation(self):
        """Hint should be absent after confirmed shift (consecutive >= 3 → reset to 0)."""
        rel = _make_rel(tendency_damping_json=json.dumps({
            "dominant_20": "friend", "dominant_ratio": 0.45,
            "spike_target": "", "spike_consecutive": 0,
            "accumulated_dampened": {},
        }))
        profile = _make_profile()
        lines = _render_companion_profile(profile, relationship=rel)
        text = "\n".join(lines)
        self.assertNotIn("风格和之前不太一样", text)

    def test_hint_absent_when_no_damping(self):
        """No hint when no damping state."""
        rel = _make_rel(tendency_damping_json="{}")
        profile = _make_profile()
        lines = _render_companion_profile(profile, relationship=rel)
        text = "\n".join(lines)
        self.assertNotIn("风格和之前不太一样", text)

    def test_hint_present_at_consecutive_2(self):
        rel = _make_rel(tendency_damping_json=json.dumps({
            "spike_target": "romantic", "spike_consecutive": 2,
        }))
        profile = _make_profile()
        lines = _render_companion_profile(profile, relationship=rel)
        text = "\n".join(lines)
        self.assertIn("风格和之前不太一样", text)


if __name__ == "__main__":
    unittest.main()
