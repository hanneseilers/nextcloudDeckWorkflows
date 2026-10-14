from __future__ import annotations

import pytest

from automation.actions_registry.slice_text import SliceTextAction
from automation.core.domain.models import DeckEvent, EventType
from automation.core.ports.action_module import ActionContext
from automation.testing.fakes import InMemoryActionRegistry, InMemoryDeckGateway


def make_context() -> ActionContext:
    return ActionContext(
        event=DeckEvent(instance="test", board_id=1, event_type=EventType.CARD_CREATED, card_id=1, stack_id=10),
        deck=InMemoryDeckGateway(),
        modules=InMemoryActionRegistry({}),
    )


def test_slices_between_start_and_end_delimiters():
    output = SliceTextAction().execute(
        make_context(), {"text": "Order #12345 confirmed", "start": "#", "end": " confirmed"}
    )

    assert output == {"text": "12345"}


def test_omitted_start_slices_from_the_beginning():
    output = SliceTextAction().execute(make_context(), {"text": "Hello, world!", "end": ","})

    assert output == {"text": "Hello"}


def test_omitted_end_slices_to_the_end():
    output = SliceTextAction().execute(make_context(), {"text": "Hello, world!", "start": ", "})

    assert output == {"text": "world!"}


def test_no_delimiters_returns_the_whole_text():
    output = SliceTextAction().execute(make_context(), {"text": "unchanged"})

    assert output == {"text": "unchanged"}


def test_missing_start_delimiter_raises_a_clear_error():
    with pytest.raises(ValueError, match="start delimiter"):
        SliceTextAction().execute(make_context(), {"text": "no markers here", "start": "#"})


def test_missing_end_delimiter_raises_a_clear_error():
    with pytest.raises(ValueError, match="end delimiter"):
        SliceTextAction().execute(make_context(), {"text": "no markers here", "end": "#"})


def test_end_delimiter_must_occur_after_start():
    # "#" only occurs before "start", so searching for it *after* start must
    # not match that earlier occurrence.
    with pytest.raises(ValueError, match="end delimiter"):
        SliceTextAction().execute(make_context(), {"text": "#before start after", "start": "start", "end": "#"})
