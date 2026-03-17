from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyst.delivery.bot_companion_timing import (
    SendWindow,
    get_send_window,
    is_within_send_window,
    compute_late_night_activity_pct,
)


UTC = timezone.utc


class TestGetSendWindow(unittest.TestCase):
    """Tests for get_send_window: each stage returns correct window."""

    def test_stranger_is_blocked(self):
        w = get_send_window("stranger")
        self.assertTrue(w.blocked)

    def test_acquaintance_window(self):
        w = get_send_window("acquaintance")
        self.assertFalse(w.blocked)
        self.assertEqual(w.start_hour, 9)
        self.assertEqual(w.start_minute, 0)
        self.assertEqual(w.end_hour, 21)
        self.assertEqual(w.end_minute, 0)

    def test_familiar_window(self):
        w = get_send_window("familiar")
        self.assertFalse(w.blocked)
        self.assertEqual(w.start_hour, 8)
        self.assertEqual(w.end_hour, 23)

    def test_close_window_default(self):
        w = get_send_window("close")
        self.assertEqual(w.start_hour, 8)
        self.assertEqual(w.end_hour, 23)
        self.assertEqual(w.end_minute, 30)

    def test_close_romantic_extension(self):
        w = get_send_window(
            "close",
            tendency_romantic=0.5,
            late_night_activity_pct=0.6,
        )
        self.assertEqual(w.start_hour, 8)
        self.assertEqual(w.end_hour, 1)
        self.assertEqual(w.end_minute, 0)

    def test_close_romantic_below_threshold_no_extension(self):
        w = get_send_window(
            "close",
            tendency_romantic=0.3,
            late_night_activity_pct=0.6,
        )
        self.assertEqual(w.end_hour, 23)
        self.assertEqual(w.end_minute, 30)

    def test_close_late_night_below_threshold_no_extension(self):
        w = get_send_window(
            "close",
            tendency_romantic=0.5,
            late_night_activity_pct=0.4,
        )
        self.assertEqual(w.end_hour, 23)
        self.assertEqual(w.end_minute, 30)

    def test_unknown_stage_falls_back_to_acquaintance(self):
        w = get_send_window("unknown_stage")
        self.assertEqual(w.start_hour, 9)
        self.assertEqual(w.end_hour, 21)


class TestIsWithinSendWindow(unittest.TestCase):
    """Tests for is_within_send_window: timezone handling, blocked, crossover."""

    def _utc(self, hour: int, minute: int = 0) -> datetime:
        return datetime(2026, 3, 17, hour, minute, tzinfo=UTC)

    # -- acquaintance window: 09:00-21:00 Asia/Shanghai (UTC+8) --

    def test_acquaintance_within_window(self):
        window = get_send_window("acquaintance")
        # 10:00 Shanghai = 02:00 UTC
        now_utc = self._utc(2, 0)
        self.assertTrue(is_within_send_window(now_utc, window=window, timezone_name="Asia/Shanghai"))

    def test_acquaintance_before_window(self):
        window = get_send_window("acquaintance")
        # 08:00 Shanghai = 00:00 UTC
        now_utc = self._utc(0, 0)
        self.assertFalse(is_within_send_window(now_utc, window=window, timezone_name="Asia/Shanghai"))

    def test_acquaintance_after_window(self):
        window = get_send_window("acquaintance")
        # 22:00 Shanghai = 14:00 UTC
        now_utc = self._utc(14, 0)
        self.assertFalse(is_within_send_window(now_utc, window=window, timezone_name="Asia/Shanghai"))

    def test_acquaintance_at_exact_start(self):
        window = get_send_window("acquaintance")
        # 09:00 Shanghai = 01:00 UTC
        now_utc = self._utc(1, 0)
        self.assertTrue(is_within_send_window(now_utc, window=window, timezone_name="Asia/Shanghai"))

    def test_acquaintance_at_exact_end(self):
        window = get_send_window("acquaintance")
        # 21:00 Shanghai = 13:00 UTC (end is exclusive)
        now_utc = self._utc(13, 0)
        self.assertFalse(is_within_send_window(now_utc, window=window, timezone_name="Asia/Shanghai"))

    # -- familiar window: 08:00-23:00 --

    def test_familiar_within_window(self):
        window = get_send_window("familiar")
        # 15:00 Shanghai = 07:00 UTC
        now_utc = self._utc(7, 0)
        self.assertTrue(is_within_send_window(now_utc, window=window, timezone_name="Asia/Shanghai"))

    def test_familiar_late_evening_within(self):
        window = get_send_window("familiar")
        # 22:30 Shanghai = 14:30 UTC
        now_utc = self._utc(14, 30)
        self.assertTrue(is_within_send_window(now_utc, window=window, timezone_name="Asia/Shanghai"))

    def test_familiar_after_23_outside(self):
        window = get_send_window("familiar")
        # 23:30 Shanghai = 15:30 UTC
        now_utc = self._utc(15, 30)
        self.assertFalse(is_within_send_window(now_utc, window=window, timezone_name="Asia/Shanghai"))

    # -- close window: 08:00-23:30 --

    def test_close_at_2315_within(self):
        window = get_send_window("close")
        # 23:15 Shanghai = 15:15 UTC
        now_utc = self._utc(15, 15)
        self.assertTrue(is_within_send_window(now_utc, window=window, timezone_name="Asia/Shanghai"))

    def test_close_at_2330_outside(self):
        window = get_send_window("close")
        # 23:30 Shanghai = 15:30 UTC (end is exclusive)
        now_utc = self._utc(15, 30)
        self.assertFalse(is_within_send_window(now_utc, window=window, timezone_name="Asia/Shanghai"))

    # -- close + romantic extension: 08:00-01:00 (crosses midnight) --

    def test_close_romantic_before_midnight_within(self):
        window = get_send_window("close", tendency_romantic=0.5, late_night_activity_pct=0.6)
        # 23:30 Shanghai = 15:30 UTC
        now_utc = self._utc(15, 30)
        self.assertTrue(is_within_send_window(now_utc, window=window, timezone_name="Asia/Shanghai"))

    def test_close_romantic_after_midnight_within(self):
        window = get_send_window("close", tendency_romantic=0.5, late_night_activity_pct=0.6)
        # 00:30 Shanghai = 16:30 UTC
        now_utc = self._utc(16, 30)
        self.assertTrue(is_within_send_window(now_utc, window=window, timezone_name="Asia/Shanghai"))

    def test_close_romantic_at_0100_outside(self):
        window = get_send_window("close", tendency_romantic=0.5, late_night_activity_pct=0.6)
        # 01:00 Shanghai = 17:00 UTC (end exclusive)
        now_utc = self._utc(17, 0)
        self.assertFalse(is_within_send_window(now_utc, window=window, timezone_name="Asia/Shanghai"))

    def test_close_romantic_at_0500_outside(self):
        window = get_send_window("close", tendency_romantic=0.5, late_night_activity_pct=0.6)
        # 05:00 Shanghai = 21:00 UTC
        now_utc = self._utc(21, 0)
        self.assertFalse(is_within_send_window(now_utc, window=window, timezone_name="Asia/Shanghai"))

    # -- blocked window --

    def test_stranger_blocked_always_false(self):
        window = get_send_window("stranger")
        # Try at any time
        now_utc = self._utc(10, 0)
        self.assertFalse(is_within_send_window(now_utc, window=window, timezone_name="Asia/Shanghai"))

    def test_blocked_window_at_midnight(self):
        window = SendWindow(0, 0, 0, 0, blocked=True)
        now_utc = self._utc(0, 0)
        self.assertFalse(is_within_send_window(now_utc, window=window, timezone_name="Asia/Shanghai"))

    # -- different timezones --

    def test_us_eastern_timezone(self):
        window = get_send_window("acquaintance")
        # 10:00 EDT (UTC-4) = 14:00 UTC
        now_utc = self._utc(14, 0)
        self.assertTrue(is_within_send_window(now_utc, window=window, timezone_name="America/New_York"))

    def test_us_eastern_before_window(self):
        window = get_send_window("acquaintance")
        # 08:00 EDT (UTC-4) = 12:00 UTC
        now_utc = self._utc(12, 0)
        self.assertFalse(is_within_send_window(now_utc, window=window, timezone_name="America/New_York"))

    def test_europe_london_timezone(self):
        window = get_send_window("familiar")
        # 10:00 Europe/London = 10:00 UTC (March, GMT)
        now_utc = self._utc(10, 0)
        self.assertTrue(is_within_send_window(now_utc, window=window, timezone_name="Europe/London"))

    def test_tokyo_timezone(self):
        window = get_send_window("acquaintance")
        # 10:00 Asia/Tokyo (UTC+9) = 01:00 UTC
        now_utc = self._utc(1, 0)
        self.assertTrue(is_within_send_window(now_utc, window=window, timezone_name="Asia/Tokyo"))

    # -- invalid timezone falls back to Asia/Shanghai --

    def test_invalid_timezone_falls_back(self):
        window = get_send_window("acquaintance")
        # 10:00 Shanghai = 02:00 UTC -- should use fallback
        now_utc = self._utc(2, 0)
        self.assertTrue(is_within_send_window(now_utc, window=window, timezone_name="Invalid/Timezone"))

    def test_empty_timezone_falls_back(self):
        window = get_send_window("acquaintance")
        now_utc = self._utc(2, 0)
        self.assertTrue(is_within_send_window(now_utc, window=window, timezone_name=""))


class TestComputeLateNightActivityPct(unittest.TestCase):
    """Tests for compute_late_night_activity_pct."""

    def test_no_messages_returns_zero(self):
        self.assertEqual(compute_late_night_activity_pct([]), 0.0)

    def test_all_late_night_returns_one(self):
        # All at 23:30 Shanghai (15:30 UTC)
        timestamps = [
            "2026-03-17T15:30:00+00:00",
            "2026-03-16T15:30:00+00:00",
            "2026-03-15T15:30:00+00:00",
        ]
        result = compute_late_night_activity_pct(timestamps, "Asia/Shanghai")
        self.assertAlmostEqual(result, 1.0)

    def test_none_late_night_returns_zero(self):
        # All at 10:00 Shanghai (02:00 UTC)
        timestamps = [
            "2026-03-17T02:00:00+00:00",
            "2026-03-16T02:00:00+00:00",
        ]
        result = compute_late_night_activity_pct(timestamps, "Asia/Shanghai")
        self.assertAlmostEqual(result, 0.0)

    def test_mixed_messages(self):
        # 2 late (23:30 Shanghai), 2 not late (10:00 Shanghai)
        timestamps = [
            "2026-03-17T15:30:00+00:00",  # 23:30 Shanghai
            "2026-03-16T15:30:00+00:00",  # 23:30 Shanghai
            "2026-03-17T02:00:00+00:00",  # 10:00 Shanghai
            "2026-03-16T02:00:00+00:00",  # 10:00 Shanghai
        ]
        result = compute_late_night_activity_pct(timestamps, "Asia/Shanghai")
        self.assertAlmostEqual(result, 0.5)

    def test_early_morning_counts_as_late(self):
        # 03:00 Shanghai = 19:00 UTC (prev day)
        timestamps = [
            "2026-03-16T19:00:00+00:00",  # 03:00 Shanghai
        ]
        result = compute_late_night_activity_pct(timestamps, "Asia/Shanghai")
        self.assertAlmostEqual(result, 1.0)

    def test_4am_counts_as_late(self):
        # 04:00 Shanghai = 20:00 UTC (prev day)
        timestamps = [
            "2026-03-16T20:00:00+00:00",
        ]
        result = compute_late_night_activity_pct(timestamps, "Asia/Shanghai")
        self.assertAlmostEqual(result, 1.0)

    def test_5am_not_late(self):
        # 05:00 Shanghai = 21:00 UTC (prev day)
        timestamps = [
            "2026-03-16T21:00:00+00:00",
        ]
        result = compute_late_night_activity_pct(timestamps, "Asia/Shanghai")
        self.assertAlmostEqual(result, 0.0)

    def test_different_timezone(self):
        # 00:00 EDT (UTC-4) = 04:00 UTC on March 17 2026 (DST active)
        timestamps = [
            "2026-03-17T04:00:00+00:00",  # 00:00 EDT
        ]
        result = compute_late_night_activity_pct(timestamps, "America/New_York")
        self.assertAlmostEqual(result, 1.0)

    def test_naive_timestamps_treated_as_utc(self):
        # Naive 15:30 -> treated as UTC -> 23:30 Shanghai
        timestamps = [
            "2026-03-17T15:30:00",
        ]
        result = compute_late_night_activity_pct(timestamps, "Asia/Shanghai")
        self.assertAlmostEqual(result, 1.0)

    def test_invalid_timestamps_ignored(self):
        timestamps = [
            "not-a-timestamp",
            "2026-03-17T02:00:00+00:00",  # 10:00 Shanghai, not late
        ]
        result = compute_late_night_activity_pct(timestamps, "Asia/Shanghai")
        self.assertAlmostEqual(result, 0.0)

    def test_all_invalid_returns_zero(self):
        timestamps = ["garbage", "", "not-a-date"]
        result = compute_late_night_activity_pct(timestamps, "Asia/Shanghai")
        self.assertAlmostEqual(result, 0.0)

    def test_invalid_timezone_falls_back_to_shanghai(self):
        # 23:30 Shanghai = 15:30 UTC
        timestamps = ["2026-03-17T15:30:00+00:00"]
        result = compute_late_night_activity_pct(timestamps, "Bogus/Timezone")
        self.assertAlmostEqual(result, 1.0)


class TestSendWindowDataclass(unittest.TestCase):
    """Edge cases for SendWindow dataclass."""

    def test_frozen(self):
        w = SendWindow(9, 0, 21, 0)
        with self.assertRaises(AttributeError):
            w.start_hour = 10  # type: ignore[misc]

    def test_blocked_default_false(self):
        w = SendWindow(9, 0, 21, 0)
        self.assertFalse(w.blocked)

    def test_blocked_explicit_true(self):
        w = SendWindow(0, 0, 0, 0, blocked=True)
        self.assertTrue(w.blocked)


if __name__ == "__main__":
    unittest.main()
