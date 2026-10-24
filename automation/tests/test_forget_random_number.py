from __future__ import annotations

import pytest

from automation.actions_registry.forget_random_number import ForgetRandomNumberAction
from automation.core.domain.models import DeckEvent, EventType
from automation.core.ports.action_module import ActionContext
from automation.testing.fakes import InMemoryActionRegistry, InMemoryDeckGateway, InMemorySequenceStore


def make_context(sequence_store=None) -> ActionContext:
    return ActionContext(
        event=DeckEvent(instance="test", board_id=1, event_type=EventType.CARD_CREATED, card_id=1, stack_id=10),
        deck=InMemoryDeckGateway(),
        modules=InMemoryActionRegistry({}),
        sequence_store=sequence_store,
    )


def test_removes_a_previously_saved_number():
    store = InMemorySequenceStore()
    store.add_number("default", "0042")

    ForgetRandomNumberAction().execute(make_context(store), {"number": "0042"})

    assert store.contains_number("default", "0042") is False


def test_only_removes_from_the_given_list_name():
    store = InMemorySequenceStore()
    store.add_number("tickets", "0042")
    store.add_number("default", "0042")

    ForgetRandomNumberAction().execute(make_context(store), {"list_name": "tickets", "number": "0042"})

    assert store.contains_number("tickets", "0042") is False
    assert store.contains_number("default", "0042") is True


def test_removing_a_number_that_was_never_saved_does_not_raise():
    store = InMemorySequenceStore()

    ForgetRandomNumberAction().execute(make_context(store), {"number": "does-not-exist"})  # no exception


def test_raises_a_clear_error_when_no_sequence_store_is_configured():
    with pytest.raises(RuntimeError, match="no sequence store"):
        ForgetRandomNumberAction().execute(make_context(None), {"number": "0042"})


def test_declares_its_input_shape():
    assert ForgetRandomNumberAction().default_input() == {"list_name": "default", "number": ""}


def test_reports_whether_the_number_was_removed():
    store = InMemorySequenceStore()
    store.add_number("default", "0042")

    assert ForgetRandomNumberAction().execute(make_context(store), {"number": "0042"}) == {"removed": True}
    assert ForgetRandomNumberAction().execute(make_context(store), {"number": "0042"}) == {"removed": False}
