from __future__ import annotations

import pytest

from automation.actions_registry.generate_random_number import GenerateRandomNumberAction
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


def test_generates_a_number_zero_padded_to_min_digits():
    output = GenerateRandomNumberAction().execute(
        make_context(InMemorySequenceStore()), {"min_digits": 4}
    )

    assert len(output["number"]) == 4
    assert output["number"].isdigit()


def test_saves_the_generated_number_by_default():
    store = InMemorySequenceStore()

    output = GenerateRandomNumberAction().execute(make_context(store), {"min_digits": 4})

    assert store.contains_number("default", output["number"]) is True


def test_save_false_does_not_record_the_number():
    store = InMemorySequenceStore()

    output = GenerateRandomNumberAction().execute(make_context(store), {"min_digits": 4, "save": False})

    assert store.contains_number("default", output["number"]) is False


def test_lists_are_independent_by_list_name():
    store = InMemorySequenceStore()

    output = GenerateRandomNumberAction().execute(
        make_context(store), {"list_name": "tickets", "min_digits": 1}
    )

    assert store.contains_number("tickets", output["number"]) is True
    assert store.contains_number("default", output["number"]) is False


def test_never_generates_a_number_already_in_the_list():
    store = InMemorySequenceStore()
    # Exhaust every 1-digit number (0-9) up front.
    for digit in range(10):
        store.add_number("default", str(digit))

    output = GenerateRandomNumberAction().execute(make_context(store), {"min_digits": 1})

    # Forced to widen past 1 digit since all ten 1-digit numbers are taken.
    assert len(output["number"]) >= 2
    assert store.contains_number("default", output["number"]) is True  # saved by default


def test_widens_by_one_digit_after_five_consecutive_collisions(monkeypatch):
    store = InMemorySequenceStore()
    store.add_number("default", "5")  # the only possible 1-digit draw once rng is forced

    import random as random_module

    monkeypatch.setattr(random_module.Random, "randrange", lambda self, n: 5 if n == 10 else 42)

    output = GenerateRandomNumberAction().execute(make_context(store), {"min_digits": 1})

    assert output["number"] == "42"  # 2-digit draw, forced by the patched randrange


def test_raises_a_clear_error_when_no_sequence_store_is_configured():
    with pytest.raises(RuntimeError, match="no sequence store"):
        GenerateRandomNumberAction().execute(make_context(None), {"min_digits": 4})


def test_declares_its_input_and_output_shape():
    action = GenerateRandomNumberAction()

    assert action.default_input() == {"list_name": "default", "min_digits": 4, "save": True}
    assert action.default_output() == {"number": ""}
