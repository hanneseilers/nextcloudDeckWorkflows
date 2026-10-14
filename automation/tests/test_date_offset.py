from __future__ import annotations

from datetime import datetime, timedelta, timezone

from automation.actions_registry.date_offset import DateOffsetAction
from automation.core.domain.models import DeckEvent, EventType
from automation.core.ports.action_module import ActionContext
from automation.testing.fakes import InMemoryActionRegistry, InMemoryDeckGateway


def make_context() -> ActionContext:
    return ActionContext(
        event=DeckEvent(instance="test", board_id=1, event_type=EventType.CARD_CREATED, card_id=1, stack_id=10),
        deck=InMemoryDeckGateway(),
        modules=InMemoryActionRegistry({}),
    )


def test_adds_days_to_a_given_base_date():
    output = DateOffsetAction().execute(
        make_context(), {"base": "2026-01-01T00:00:00+00:00", "days": 5}
    )

    assert output == {"date": "2026-01-06T00:00:00+00:00"}


def test_subtracts_days_with_a_negative_value():
    output = DateOffsetAction().execute(
        make_context(), {"base": "2026-01-10T00:00:00+00:00", "days": -3}
    )

    assert output == {"date": "2026-01-07T00:00:00+00:00"}


def test_defaults_to_now_when_no_base_is_given():
    before = datetime.now(timezone.utc)
    output = DateOffsetAction().execute(make_context(), {"days": 2})
    after = datetime.now(timezone.utc)

    computed = datetime.fromisoformat(output["date"])
    assert before + timedelta(days=2) <= computed <= after + timedelta(days=2)


def test_zero_days_returns_the_base_date_unchanged():
    output = DateOffsetAction().execute(make_context(), {"base": "2026-01-01T00:00:00+00:00", "days": 0})

    assert output == {"date": "2026-01-01T00:00:00+00:00"}
