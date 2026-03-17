"""Outreach response rate tracking and frequency throttling."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OutreachMetrics:
    sent_7d: int
    replied_7d: int
    response_rate: float  # replied_7d / sent_7d (1.0 if no data)
    consecutive_unreplied: int  # consecutive most-recent unreplied outreach


@dataclass(frozen=True)
class OutreachThrottle:
    daily_limit: int  # 0 = paused
    cooldown_hours: int
    paused: bool


def compute_outreach_metrics(
    records: list,  # list[CompanionOutreachLogRecord]
) -> OutreachMetrics:
    """Compute 7-day rolling outreach metrics from outreach log records.

    Records should be pre-filtered to the relevant time window.
    """
    if not records:
        return OutreachMetrics(
            sent_7d=0,
            replied_7d=0,
            response_rate=1.0,
            consecutive_unreplied=0,
        )
    sent = len(records)
    replied = sum(1 for r in records if getattr(r, "user_replied", False))
    rate = replied / sent if sent > 0 else 1.0

    # Count consecutive unreplied from most recent
    consecutive = 0
    for r in records:  # records are typically sorted DESC by sent_at
        if not getattr(r, "user_replied", False):
            consecutive += 1
        else:
            break

    return OutreachMetrics(
        sent_7d=sent,
        replied_7d=replied,
        response_rate=rate,
        consecutive_unreplied=consecutive,
    )


def compute_outreach_throttle(metrics: OutreachMetrics) -> OutreachThrottle:
    """Map response rate to frequency throttle tier.

    Tiers per PRD:
      ≥ 0.6  → limit 3, cooldown 3h
      0.3–0.59 → limit 1, cooldown 8h
      0.1–0.29 → limit 1/3days, cooldown 72h
      < 0.1  → paused
    """
    rate = metrics.response_rate
    if metrics.sent_7d == 0:
        # No outreach data — use cautious default
        return OutreachThrottle(daily_limit=2, cooldown_hours=4, paused=False)
    if rate >= 0.6:
        return OutreachThrottle(daily_limit=3, cooldown_hours=3, paused=False)
    if rate >= 0.3:
        return OutreachThrottle(daily_limit=1, cooldown_hours=8, paused=False)
    if rate >= 0.1:
        return OutreachThrottle(daily_limit=1, cooldown_hours=72, paused=False)
    return OutreachThrottle(daily_limit=0, cooldown_hours=0, paused=True)


def should_send_outreach(
    throttle: OutreachThrottle,
    *,
    outreach_count_today: int,
    hours_since_last_outreach: float,
) -> bool:
    """Determine if a new outreach message should be sent given the current throttle."""
    if throttle.paused:
        return False
    if throttle.daily_limit <= 0:
        return False
    if outreach_count_today >= throttle.daily_limit:
        return False
    if throttle.cooldown_hours > 0 and hours_since_last_outreach < throttle.cooldown_hours:
        return False
    return True
