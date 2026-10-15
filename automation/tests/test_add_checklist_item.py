from __future__ import annotations

from automation.actions_registry.add_checklist_item import AddChecklistItemAction
from automation.core.domain.models import DeckEvent, EventType
from automation.core.ports.action_module import ActionContext
from automation.testing.fakes import InMemoryActionRegistry, InMemoryDeckGateway


def make_context(deck: InMemoryDeckGateway) -> ActionContext:
    return ActionContext(
        event=DeckEvent(instance="test", board_id=1, event_type=EventType.CARD_CREATED, card_id=100, stack_id=10),
        deck=deck,
        modules=InMemoryActionRegistry({}),
    )


def test_appends_a_checklist_item_to_an_empty_description():
    deck = InMemoryDeckGateway({1: [{"id": 10, "cards": [{"id": 100, "lastModified": 1}]}]})

    output = AddChecklistItemAction().execute(make_context(deck), {"text": "Buy milk"})

    assert output == {"description": "- [ ] Buy milk\n"}
    assert deck.stacks[1][0]["cards"][0]["description"] == "- [ ] Buy milk\n"


def test_appends_to_an_existing_description_and_checklist():
    deck = InMemoryDeckGateway({1: [{
        "id": 10,
        "cards": [{"id": 100, "lastModified": 1, "description": "Notes\n- [x] Done already\n"}],
    }]})

    output = AddChecklistItemAction().execute(make_context(deck), {"text": "One more thing"})

    assert output == {"description": "Notes\n- [x] Done already\n- [ ] One more thing\n"}


def test_adds_a_newline_before_the_new_item_if_the_description_does_not_end_with_one():
    deck = InMemoryDeckGateway({1: [{
        "id": 10,
        "cards": [{"id": 100, "lastModified": 1, "description": "Notes without trailing newline"}],
    }]})

    output = AddChecklistItemAction().execute(make_context(deck), {"text": "Task"})

    assert output == {"description": "Notes without trailing newline\n- [ ] Task\n"}


def test_declares_its_input_and_output_shape():
    action = AddChecklistItemAction()

    assert action.default_input() == {"text": ""}
    assert action.default_output() == {"description": ""}
