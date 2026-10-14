from __future__ import annotations

from automation.actions_registry.add_comment import AddCommentAction
from automation.actions_registry.add_label import AddLabelAction
from automation.actions_registry.assign_user import AssignUserAction
from automation.actions_registry.move_card import MoveCardAction
from automation.actions_registry.set_description import SetDescriptionAction
from automation.actions_registry.set_due_date import SetDueDateAction
from automation.actions_registry.set_title import SetTitleAction
from automation.actions_registry.set_variable import SetVariableAction
from automation.actions_registry.unassign_user import UnassignUserAction
from automation.core.domain.models import DeckEvent, EventType
from automation.core.ports.action_module import ActionContext
from automation.testing.fakes import InMemoryActionRegistry, InMemoryDeckGateway


def make_context(deck: InMemoryDeckGateway, modules=None, **overrides) -> ActionContext:
    defaults = dict(instance="test", board_id=1, event_type=EventType.CARD_CREATED, card_id=100, stack_id=10)
    defaults.update(overrides)
    return ActionContext(
        event=DeckEvent(**defaults), deck=deck, modules=modules or InMemoryActionRegistry({})
    )


def make_deck() -> InMemoryDeckGateway:
    return InMemoryDeckGateway({1: [{"id": 10, "cards": [{"id": 100, "lastModified": 1}]}, {"id": 20, "cards": []}]})


def test_set_title_renames_the_card():
    deck = make_deck()
    output = SetTitleAction().execute(make_context(deck), {"title": "New title"})

    assert deck.stacks[1][0]["cards"][0]["title"] == "New title"
    assert output == {}


def test_set_description_changes_content():
    deck = make_deck()
    SetDescriptionAction().execute(make_context(deck), {"description": "New content"})

    assert deck.stacks[1][0]["cards"][0]["description"] == "New content"


def test_set_due_date_sets_the_due_date():
    deck = make_deck()
    SetDueDateAction().execute(make_context(deck), {"due_date": "2026-01-31T00:00:00+00:00"})

    assert deck.stacks[1][0]["cards"][0]["duedate"] == "2026-01-31T00:00:00+00:00"


def test_move_card_relocates_the_card_to_the_target_stack():
    deck = make_deck()
    MoveCardAction().execute(make_context(deck), {"target_stack_id": 20})

    assert deck.stacks[1][0]["cards"] == []
    assert [c["id"] for c in deck.stacks[1][1]["cards"]] == [100]


def test_assign_and_unassign_user():
    deck = make_deck()
    context = make_context(deck)

    AssignUserAction().execute(context, {"user_id": "alice"})
    assert deck.stacks[1][0]["cards"][0]["assignees"] == ["alice"]

    UnassignUserAction().execute(context, {"user_id": "alice"})
    assert deck.stacks[1][0]["cards"][0]["assignees"] == []


def test_add_label_adds_the_label_id():
    deck = make_deck()
    AddLabelAction().execute(make_context(deck), {"label_id": 5})

    assert deck.stacks[1][0]["cards"][0]["labels"] == [5]


def test_add_comment_is_recorded():
    deck = make_deck()
    AddCommentAction().execute(make_context(deck), {"message": "hello"})

    assert ("add_comment", 100, "hello") in deck.calls


def test_set_variable_writes_into_the_shared_context_variables():
    context = make_context(make_deck())
    output = SetVariableAction().execute(context, {"name": "greeting", "value": "hi"})

    assert context.variables == {"greeting": "hi"}
    assert output == {"name": "greeting", "value": "hi"}
