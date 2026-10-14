"""Pure logic deciding whether a board should be polled this run, once
webhooks are configured - no I/O, so it's trivial to unit test against
fixed datetimes instead of mocking real time (same style as
core/domain/schedule.py).

Without this, main.py polls every configured board on every single
invocation, regardless of whether anything might have changed - the
(only) way this project can detect a change at all without webhooks.
Once webhooks are configured (see website/webhook.php, which is what
records a ping, and the WebhookConfig docstring for why full-time polling
isn't dropped entirely even then), a board is polled immediately if it's
been pinged since its last poll, or if it's simply never been polled
before - otherwise only every `fallback_poll_minutes`, as a safety net
against a missed/misconfigured/failed webhook delivery.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional


def should_poll_now(
    fallback_poll_minutes: float,
    now: datetime,
    last_ping: Optional[datetime],
    last_polled: Optional[datetime],
) -> bool:
    # All three datetimes must be timezone-aware and in the same timezone
    # (main.py always uses UTC, matching website/webhook.php) - comparing a
    # naive one against an aware one raises TypeError rather than silently
    # comparing wrong values, which already caught one real bug while this
    # was being tested (see the heartbeat feature's commit for the same
    # class of mistake).
    if last_polled is None:
        return True  # never polled this board before - always do it at least once

    has_fresh_ping = last_ping is not None and last_ping > last_polled
    if has_fresh_ping:
        return True

    overdue = now - last_polled >= timedelta(minutes=fallback_poll_minutes)
    return overdue
