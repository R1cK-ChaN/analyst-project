from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst.delivery.bot_companion_timing import (
    _should_warm_up_share,
    evaluate_relationship_checkin_kind,
)
from analyst.delivery.outreach_metrics import OutreachMetrics
from analyst.runtime.chat import _proactive_companion_instruction
from analyst.storage.sqlite_records import CompanionRelationshipStateRecord


def _make_rel(**overrides) -> CompanionRelationshipStateRecord:
    defaults = dict(
        client_id="u1",
        intimacy_level=0.3,
        relationship_stage="acquaintance",
        tendency_friend=0.25,
        tendency_romantic=0.25,
        tendency_confidant=0.25,
        tendency_mentor=0.25,
        streak_days=0,
        total_turns=20,
        avg_session_turns=3.0,
        mood_history=[],
        nicknames=[],
        previous_stage="familiar",  # regressed from familiar
        last_interaction_date="2026-03-10",
        last_stage_transition_at="",
        created_at="",
        updated_at="",
        outreach_paused=False,
        outreach_paused_at="",
        peak_intimacy_level=0.5,  # decayed from 0.5 to 0.3
        tendency_damping_json="{}",
    )
    defaults.update(overrides)
    return CompanionRelationshipStateRecord(**defaults)


class TestShouldWarmUpShare(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        self.old_outreach = (self.now - timedelta(hours=80)).isoformat()
        self.metrics_low = OutreachMetrics(sent_7d=10, replied_7d=2, response_rate=0.2, consecutive_unreplied=5)

    def test_all_conditions_met(self):
        rel = _make_rel()
        self.assertTrue(_should_warm_up_share(rel, self.metrics_low, self.old_outreach, self.now))

    def test_stage_not_regressed_but_intimacy_decayed(self):
        rel = _make_rel(previous_stage="", peak_intimacy_level=0.5, intimacy_level=0.3)
        self.assertTrue(_should_warm_up_share(rel, self.metrics_low, self.old_outreach, self.now))

    def test_stage_regressed_no_intimacy_decay(self):
        rel = _make_rel(peak_intimacy_level=0.3, intimacy_level=0.3)
        self.assertTrue(_should_warm_up_share(rel, self.metrics_low, self.old_outreach, self.now))

    def test_no_regression_no_decay(self):
        rel = _make_rel(previous_stage="", peak_intimacy_level=0.3, intimacy_level=0.3)
        self.assertFalse(_should_warm_up_share(rel, self.metrics_low, self.old_outreach, self.now))

    def test_response_rate_too_high(self):
        metrics_high = OutreachMetrics(sent_7d=10, replied_7d=5, response_rate=0.5, consecutive_unreplied=2)
        rel = _make_rel()
        self.assertFalse(_should_warm_up_share(rel, metrics_high, self.old_outreach, self.now))

    def test_outreach_too_recent(self):
        recent = (self.now - timedelta(hours=48)).isoformat()
        rel = _make_rel()
        self.assertFalse(_should_warm_up_share(rel, self.metrics_low, recent, self.now))

    def test_72h_boundary(self):
        exactly_72h = (self.now - timedelta(hours=72)).isoformat()
        rel = _make_rel()
        # At exactly 72h, hours_since >= 72 is False (floating point), so blocked
        # But at 72h + 1 second it should pass
        over_72h = (self.now - timedelta(hours=72, seconds=1)).isoformat()
        self.assertTrue(_should_warm_up_share(rel, self.metrics_low, over_72h, self.now))

    def test_no_last_outreach(self):
        rel = _make_rel()
        self.assertTrue(_should_warm_up_share(rel, self.metrics_low, None, self.now))

    def test_none_relationship(self):
        self.assertFalse(_should_warm_up_share(None, self.metrics_low, self.old_outreach, self.now))


class TestEvaluateWithWarmUpShare(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        self.old_outreach = (self.now - timedelta(hours=80)).isoformat()
        self.metrics_low = OutreachMetrics(sent_7d=10, replied_7d=2, response_rate=0.2, consecutive_unreplied=5)

    def test_warm_up_share_returned(self):
        rel = _make_rel()
        kind = evaluate_relationship_checkin_kind(
            rel, now=self.now, outreach_metrics=self.metrics_low, last_outreach_sent_at=self.old_outreach,
        )
        self.assertEqual(kind, "warm_up_share")

    def test_streak_save_takes_priority(self):
        yesterday = (self.now - timedelta(days=1)).strftime("%Y-%m-%d")
        rel = _make_rel(streak_days=5, last_interaction_date=yesterday, previous_stage="")
        kind = evaluate_relationship_checkin_kind(rel, now=self.now)
        self.assertEqual(kind, "streak_save")

    def test_very_low_rate_regressing_only_warm_up(self):
        """When rate < 0.3 and regressing, warm_up_share is the only allowed kind."""
        metrics_very_low = OutreachMetrics(sent_7d=10, replied_7d=1, response_rate=0.1, consecutive_unreplied=8)
        yesterday = (self.now - timedelta(days=1)).strftime("%Y-%m-%d")
        rel = _make_rel(
            streak_days=5, last_interaction_date=yesterday,
            previous_stage="familiar", relationship_stage="acquaintance",
        )
        kind = evaluate_relationship_checkin_kind(
            rel, now=self.now, outreach_metrics=metrics_very_low, last_outreach_sent_at=self.old_outreach,
        )
        self.assertEqual(kind, "warm_up_share")

    def test_no_metrics_no_warm_up(self):
        """Without outreach metrics, warm_up_share shouldn't trigger."""
        rel = _make_rel()
        kind = evaluate_relationship_checkin_kind(rel, now=self.now)
        # No metrics → response_rate defaults to 1.0 → condition not met
        self.assertNotEqual(kind, "warm_up_share")


class TestPeakIntimacyTracking(unittest.TestCase):
    def test_peak_updates_on_increase(self):
        from analyst.memory.relationship import compute_relationship_update
        from analyst.memory.profile import RelationshipSignalUpdate

        rel = _make_rel(intimacy_level=0.3, peak_intimacy_level=0.3)
        signal = RelationshipSignalUpdate(
            current_mood="happy",
            is_personal_sharing=True,
            topic_depth_score=0.8,
        )
        now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        updates = compute_relationship_update(rel, signal=signal, now=now)
        new_intimacy = updates["intimacy_level"]
        if new_intimacy > 0.3:
            self.assertIn("peak_intimacy_level", updates)
            self.assertEqual(updates["peak_intimacy_level"], new_intimacy)

    def test_peak_stays_on_decrease(self):
        from analyst.memory.relationship import compute_relationship_update
        from analyst.memory.profile import RelationshipSignalUpdate

        rel = _make_rel(
            intimacy_level=0.3, peak_intimacy_level=0.5,
            last_interaction_date="2026-03-10",
        )
        signal = RelationshipSignalUpdate()
        now = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
        updates = compute_relationship_update(rel, signal=signal, now=now)
        self.assertNotIn("peak_intimacy_level", updates)


class TestWarmUpShareInstruction(unittest.TestCase):
    def test_instruction_content(self):
        inst = _proactive_companion_instruction("warm_up_share")
        self.assertIn("随手分享", inst)
        self.assertIn("不要关心对方", inst)
        self.assertIn("不要问", inst)
        self.assertIn("不要用问号", inst)

    def test_instruction_not_empty(self):
        inst = _proactive_companion_instruction("warm_up_share")
        self.assertTrue(len(inst) > 50)


if __name__ == "__main__":
    unittest.main()
