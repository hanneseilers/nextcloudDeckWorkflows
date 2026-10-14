from __future__ import annotations

import pytest

from automation.actions_registry.extract_field import ExtractFieldAction
from automation.core.domain.models import DeckEvent, EventType
from automation.core.ports.action_module import ActionContext
from automation.testing.fakes import InMemoryActionRegistry, InMemoryDeckGateway


def make_context() -> ActionContext:
    return ActionContext(
        event=DeckEvent(instance="test", board_id=1, event_type=EventType.CARD_CREATED, card_id=1, stack_id=10),
        deck=InMemoryDeckGateway(),
        modules=InMemoryActionRegistry({}),
    )


def test_extracts_a_dict_key():
    output = ExtractFieldAction().execute(make_context(), {"data": {"title": "Sync", "start": "10:00"}, "path": "title"})

    assert output == {"value": "Sync"}


def test_extracts_through_a_list_index():
    output = ExtractFieldAction().execute(
        make_context(), {"data": {"events": [{"title": "First"}, {"title": "Second"}]}, "path": "events.1.title"}
    )

    assert output == {"value": "Second"}


def test_empty_path_returns_data_unchanged():
    output = ExtractFieldAction().execute(make_context(), {"data": {"a": 1}, "path": ""})

    assert output == {"value": {"a": 1}}


def test_missing_dict_key_raises():
    with pytest.raises(KeyError):
        ExtractFieldAction().execute(make_context(), {"data": {"a": 1}, "path": "b"})


def test_list_index_out_of_range_raises():
    with pytest.raises(IndexError):
        ExtractFieldAction().execute(make_context(), {"data": [1, 2], "path": "5"})


def test_non_numeric_index_into_a_list_raises():
    with pytest.raises(ValueError):
        ExtractFieldAction().execute(make_context(), {"data": [1, 2], "path": "first"})


def test_indexing_into_a_scalar_raises():
    with pytest.raises(TypeError):
        ExtractFieldAction().execute(make_context(), {"data": 42, "path": "title"})
