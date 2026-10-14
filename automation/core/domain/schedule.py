"""Pure logic for ScheduleTrigger - no I/O, so it's trivial to unit test
against a fixed `now`/`last_fired` instead of mocking real time."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from automation.core.domain.models import ScheduleTrigger


def should_fire(trigger: ScheduleTrigger, now: datetime, last_fired: Optional[datetime]) -> bool:
    """True if `trigger`'s scheduled time for "today" (relative to `now`)
    has passed and hasn't already been fired for. Comparing against the
    last-fired timestamp instead of requiring an exact-minute match means a
    delayed/missed cron tick still fires on the next one, and a workflow
    never fires twice for the same scheduled slot.
    """

    if trigger.weekdays and now.isoweekday() not in trigger.weekdays:
        return False

    hour, minute = (int(part) for part in trigger.time.split(":"))
    scheduled_today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now < scheduled_today:
        return False
    if last_fired is not None and last_fired >= scheduled_today:
        return False
    return True
