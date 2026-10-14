from __future__ import annotations

from datetime import datetime

from automation.core.domain.models import ScheduleTrigger
from automation.core.domain.schedule import should_fire


def test_fires_once_the_scheduled_time_has_passed_today_and_never_fired():
    trigger = ScheduleTrigger(time="09:00")
    now = datetime(2026, 1, 5, 9, 1)  # a Monday, just after 09:00

    assert should_fire(trigger, now, last_fired=None) is True


def test_does_not_fire_before_the_scheduled_time_today():
    trigger = ScheduleTrigger(time="09:00")
    now = datetime(2026, 1, 5, 8, 59)

    assert should_fire(trigger, now, last_fired=None) is False


def test_does_not_fire_twice_for_the_same_scheduled_slot():
    trigger = ScheduleTrigger(time="09:00")
    now = datetime(2026, 1, 5, 9, 30)
    last_fired = datetime(2026, 1, 5, 9, 1)  # already fired earlier today, after 09:00

    assert should_fire(trigger, now, last_fired) is False


def test_fires_again_on_the_next_matching_day():
    trigger = ScheduleTrigger(time="09:00")
    now = datetime(2026, 1, 6, 9, 1)  # the next day
    last_fired = datetime(2026, 1, 5, 9, 1)  # fired yesterday

    assert should_fire(trigger, now, last_fired) is True


def test_a_delayed_cron_tick_still_fires_once():
    """A cron tick that lands late (e.g. at 09:07 instead of 09:00, or the
    very first tick after a gap) must still fire - should_fire compares
    against the scheduled moment having passed, not an exact-minute match."""
    trigger = ScheduleTrigger(time="09:00")
    now = datetime(2026, 1, 5, 9, 7)

    assert should_fire(trigger, now, last_fired=None) is True


def test_respects_weekdays_filter():
    trigger = ScheduleTrigger(time="09:00", weekdays=(1,))  # Monday only
    monday = datetime(2026, 1, 5, 9, 1)
    tuesday = datetime(2026, 1, 6, 9, 1)

    assert monday.isoweekday() == 1
    assert should_fire(trigger, monday, last_fired=None) is True
    assert should_fire(trigger, tuesday, last_fired=None) is False


def test_no_weekdays_means_every_day():
    trigger = ScheduleTrigger(time="09:00", weekdays=None)
    sunday = datetime(2026, 1, 4, 9, 1)

    assert sunday.isoweekday() == 7
    assert should_fire(trigger, sunday, last_fired=None) is True
