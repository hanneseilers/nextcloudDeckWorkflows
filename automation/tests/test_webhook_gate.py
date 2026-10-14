from __future__ import annotations

from datetime import datetime, timedelta

from automation.core.domain.webhook_gate import should_poll_now


def test_always_polls_a_board_that_was_never_polled_before():
    now = datetime(2026, 1, 5, 12, 0)

    assert should_poll_now(15.0, now, last_ping=None, last_polled=None) is True


def test_polls_immediately_if_pinged_after_the_last_poll():
    now = datetime(2026, 1, 5, 12, 0)
    last_polled = now - timedelta(minutes=5)
    last_ping = now - timedelta(minutes=1)  # after last_polled

    assert should_poll_now(15.0, now, last_ping, last_polled) is True


def test_does_not_poll_if_the_ping_is_older_than_the_last_poll():
    now = datetime(2026, 1, 5, 12, 0)
    last_polled = now - timedelta(minutes=1)
    last_ping = now - timedelta(minutes=5)  # before last_polled - stale, already acted on

    assert should_poll_now(15.0, now, last_ping, last_polled) is False


def test_does_not_poll_before_the_fallback_interval_elapses_with_no_ping():
    now = datetime(2026, 1, 5, 12, 0)
    last_polled = now - timedelta(minutes=10)

    assert should_poll_now(15.0, now, last_ping=None, last_polled=last_polled) is False


def test_polls_again_once_the_fallback_interval_elapses_with_no_ping():
    now = datetime(2026, 1, 5, 12, 0)
    last_polled = now - timedelta(minutes=16)

    assert should_poll_now(15.0, now, last_ping=None, last_polled=last_polled) is True


def test_fallback_interval_boundary_is_inclusive():
    now = datetime(2026, 1, 5, 12, 0)
    last_polled = now - timedelta(minutes=15)

    assert should_poll_now(15.0, now, last_ping=None, last_polled=last_polled) is True
