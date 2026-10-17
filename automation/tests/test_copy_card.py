from __future__ import annotations

import pytest

from automation.actions_registry.copy_card import CopyCardAction
from automation.core.domain.models import DeckEvent, EventType
from automation.core.ports.action_module import ActionContext
from automation.testing.fakes import InMemoryActionRegistry, InMemoryDeckGateway


def make(deck):
    event = DeckEvent(instance="t", board_id=1, event_type=EventType.CARD_CREATED, card_id=100, stack_id=10,
                      card={"id": 100, "title": "event title"})
    return ActionContext(event=event, deck=deck, modules=InMemoryActionRegistry({}))


def make_deck():
    return InMemoryDeckGateway({
        1: [{"id": 10, "cards": [{
            "id": 100, "title": "Original", "description": "Orig desc", "lastModified": 1,
            "duedate": "2026-01-01T00:00:00+00:00", "assignees": ["anna"], "labels": [99],
        }]}],
        2: [{"id": 20, "cards": []}],
    })


def test_copies_title_and_description_only_to_the_other_board():
    deck = make_deck()
    out = CopyCardAction().execute(make(deck), {"target_board_id": 2, "target_stack_id": 20})

    copy = deck.stacks[2][0]["cards"][0]
    assert copy["title"] == "Original" and copy["description"] == "Orig desc"
    assert "duedate" not in copy and "assignees" not in copy and "labels" not in copy
    assert out == {"card_id": copy["id"], "board_id": 2, "stack_id": 20}
    assert len(deck.stacks[1][0]["cards"]) == 1  # original untouched


def test_given_title_and_description_override_the_copy_only():
    deck = make_deck()
    CopyCardAction().execute(make(deck), {
        "target_board_id": 2, "target_stack_id": 20, "title": "Neu", "description": "Neue Beschreibung",
    })

    copy = deck.stacks[2][0]["cards"][0]
    assert (copy["title"], copy["description"]) == ("Neu", "Neue Beschreibung")
    assert deck.stacks[1][0]["cards"][0]["title"] == "Original"


def test_empty_overrides_keep_the_original_values():
    deck = make_deck()
    CopyCardAction().execute(make(deck), {
        "target_board_id": 2, "target_stack_id": 20, "title": "", "description": "",
    })
    copy = deck.stacks[2][0]["cards"][0]
    assert (copy["title"], copy["description"]) == ("Original", "Orig desc")


def test_unknown_target_stack_raises():
    with pytest.raises(KeyError):
        CopyCardAction().execute(make(make_deck()), {"target_board_id": 2, "target_stack_id": 999})
