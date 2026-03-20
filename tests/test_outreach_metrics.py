from __future__ import annotations

import sys
from pathlib import Path
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from analyst.delivery.outreach_metrics import (
    OutreachMetrics,
    OutreachThrottle,
    compute_outreach_metrics,
    compute_outreach_throttle,
    should_send_outreach,
)
from analyst.storage.sqlite_records import CompanionOutreachLogRecord


def _make_record(user_replied: bool = False, **overrides) -> CompanionOutreachLogRecord:
    defaults = dict(
        outreach_id=1,
        client_id="u1",
        channel="telegram:123",
        thread_id="main",
        kind="streak_save",
        content_raw="test",
        content_normalized="test",
        sent_at="2026-03-17T10:00:00+00:00",
        user_replied=user_replied,
        user_replied_at="",
        created_at="2026-03-17T10:00:00+00:00",
    )
    defaults.update(overrides)
    return CompanionOutreachLogRecord(**defaults)


class TestComputeOutreachMetrics(unittest.TestCase):
    def test_empty_records(self):
        m = compute_outreach_metrics([])
        self.assertEqual(m.sent_7d, 0)
        self.assertEqual(m.replied_7d, 0)
        self.assertAlmostEqual(m.response_rate, 1.0)
        self.assertEqual(m.consecutive_unreplied, 0)

    def test_all_replied(self):
        records = [_make_record(user_replied=True) for _ in range(5)]
        m = compute_outreach_metrics(records)
        self.assertEqual(m.sent_7d, 5)
        self.assertEqual(m.replied_7d, 5)
        self.assertAlmostEqual(m.response_rate, 1.0)
        self.assertEqual(m.consecutive_unreplied, 0)

    def test_none_replied(self):
        records = [_make_record(user_replied=False) for _ in range(5)]
        m = compute_outreach_metrics(records)
        self.assertEqual(m.sent_7d, 5)
        self.assertEqual(m.replied_7d, 0)
        self.assertAlmostEqual(m.response_rate, 0.0)
        self.assertEqual(m.consecutive_unreplied, 5)

    def test_mixed(self):
        # Most recent first (DESC order)
        records = [
            _make_record(user_replied=False),  # most recent
            _make_record(user_replied=False),
            _make_record(user_replied=True),
            _make_record(user_replied=True),
            _make_record(user_replied=True),
        ]
        m = compute_outreach_metrics(records)
        self.assertEqual(m.sent_7d, 5)
        self.assertEqual(m.replied_7d, 3)
        self.assertAlmostEqual(m.response_rate, 0.6)
        self.assertEqual(m.consecutive_unreplied, 2)

    def test_consecutive_unreplied_stops_at_replied(self):
        records = [
            _make_record(user_replied=False),
            _make_record(user_replied=True),  # stops here
            _make_record(user_replied=False),
        ]
        m = compute_outreach_metrics(records)
        self.assertEqual(m.consecutive_unreplied, 1)


class TestComputeOutreachThrottle(unittest.TestCase):
    def test_no_data(self):
        t = compute_outreach_throttle(OutreachMetrics(0, 0, 1.0, 0))
        self.assertFalse(t.paused)
        self.assertEqual(t.daily_limit, 2)

    def test_high_rate(self):
        t = compute_outreach_throttle(OutreachMetrics(10, 7, 0.7, 0))
        self.assertEqual(t.daily_limit, 3)
        self.assertEqual(t.cooldown_hours, 3)
        self.assertFalse(t.paused)

    def test_medium_rate(self):
        t = compute_outreach_throttle(OutreachMetrics(10, 4, 0.4, 2))
        self.assertEqual(t.daily_limit, 1)
        self.assertEqual(t.cooldown_hours, 8)

    def test_low_rate(self):
        t = compute_outreach_throttle(OutreachMetrics(10, 2, 0.2, 5))
        self.assertEqual(t.daily_limit, 1)
        self.assertEqual(t.cooldown_hours, 72)

    def test_very_low_rate_paused(self):
        t = compute_outreach_throttle(OutreachMetrics(10, 0, 0.0, 10))
        self.assertTrue(t.paused)
        self.assertEqual(t.daily_limit, 0)

    def test_boundary_0_6(self):
        t = compute_outreach_throttle(OutreachMetrics(10, 6, 0.6, 0))
        self.assertEqual(t.daily_limit, 3)

    def test_boundary_0_3(self):
        t = compute_outreach_throttle(OutreachMetrics(10, 3, 0.3, 0))
        self.assertEqual(t.daily_limit, 1)
        self.assertEqual(t.cooldown_hours, 8)

    def test_boundary_0_1(self):
        t = compute_outreach_throttle(OutreachMetrics(10, 1, 0.1, 0))
        self.assertEqual(t.daily_limit, 1)
        self.assertEqual(t.cooldown_hours, 72)


class TestShouldSendOutreach(unittest.TestCase):
    def test_paused(self):
        t = OutreachThrottle(daily_limit=0, cooldown_hours=0, paused=True)
        self.assertFalse(should_send_outreach(t, outreach_count_today=0, hours_since_last_outreach=999))

    def test_under_limit(self):
        t = OutreachThrottle(daily_limit=3, cooldown_hours=3, paused=False)
        self.assertTrue(should_send_outreach(t, outreach_count_today=1, hours_since_last_outreach=4))

    def test_at_limit(self):
        t = OutreachThrottle(daily_limit=3, cooldown_hours=3, paused=False)
        self.assertFalse(should_send_outreach(t, outreach_count_today=3, hours_since_last_outreach=4))

    def test_cooldown_not_met(self):
        t = OutreachThrottle(daily_limit=3, cooldown_hours=3, paused=False)
        self.assertFalse(should_send_outreach(t, outreach_count_today=1, hours_since_last_outreach=2))

    def test_cooldown_met(self):
        t = OutreachThrottle(daily_limit=1, cooldown_hours=8, paused=False)
        self.assertTrue(should_send_outreach(t, outreach_count_today=0, hours_since_last_outreach=9))

    def test_zero_daily_limit(self):
        t = OutreachThrottle(daily_limit=0, cooldown_hours=0, paused=False)
        self.assertFalse(should_send_outreach(t, outreach_count_today=0, hours_since_last_outreach=999))


if __name__ == "__main__":
    unittest.main()
