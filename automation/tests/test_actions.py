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
    assert output == {"title": "New title"}


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


def test_add_comment_substitutes_global_variables():
    deck = make_deck()
    context = make_context(deck)
    context.variables["name"] = "Alice"

    AddCommentAction().execute(context, {"message": "Hello $name"})

    assert ("add_comment", 100, "Hello Alice") in deck.calls


def test_set_variable_writes_into_the_shared_context_variables():
    context = make_context(make_deck())
    output = SetVariableAction().execute(context, {"name": "greeting", "value": "hi"})

    assert context.variables == {"greeting": "hi"}
    assert output == {"name": "greeting", "value": "hi"}


def test_card_edit_actions_return_what_they_set():
    from automation.actions_registry.add_comment import AddCommentAction
    from automation.actions_registry.set_due_date import SetDueDateAction

    deck = make_deck()
    ctx = make_context(deck)
    ctx.variables["nr"] = "0042"

    assert SetDescriptionAction().execute(ctx, {"description": "Text"}) == {"description": "Text"}
    assert SetDueDateAction().execute(ctx, {"due_date": "2026-12-31T00:00:00+00:00"}) == {"due_date": "2026-12-31T00:00:00+00:00"}
    assert SetDueDateAction().execute(ctx, {}) == {"due_date": None}  # cleared
    assert AddCommentAction().execute(ctx, {"message": "Ticket $nr"}) == {"message": "Ticket 0042"}


def test_add_label_returns_id_and_name_from_the_board_labels():
    from automation.actions_registry.add_label import AddLabelAction

    deck = make_deck()
    deck.labels[1] = [{"id": 99, "title": "Priorität hoch"}, {"id": 100, "title": "Bug"}]
    assert AddLabelAction().execute(make_context(deck), {"label_id": 99}) == {"label_id": 99, "label_name": "Priorität hoch"}
    assert AddLabelAction().execute(make_context(deck), {"label_id": 7}) == {"label_id": 7, "label_name": None}


def test_add_label_still_adds_when_the_name_lookup_fails():
    from automation.actions_registry.add_label import AddLabelAction

    deck = make_deck()
    deck.list_labels = lambda board_id: (_ for _ in ()).throw(RuntimeError("down"))
    assert AddLabelAction().execute(make_context(deck), {"label_id": 99}) == {"label_id": 99, "label_name": None}
    assert ("add_label", 1, 10, 100, 99) in deck.calls


def test_remove_label_takes_the_label_off_the_card():
    from automation.actions_registry.remove_label import RemoveLabelAction

    deck = make_deck()
    deck.labels[1] = [{"id": 99, "title": "Dringend"}]
    context = make_context(deck)
    AddLabelAction().execute(context, {"label_id": 99})
    assert deck.stacks[1][0]["cards"][0]["labels"] == [99]

    out = RemoveLabelAction().execute(context, {"label_id": 99})

    assert deck.stacks[1][0]["cards"][0]["labels"] == []
    assert out == {"label_id": 99, "label_name": "Dringend", "removed": True}


def test_remove_label_skips_a_label_the_card_does_not_have():
    from automation.actions_registry.remove_label import RemoveLabelAction

    deck = make_deck()
    deck.stacks[1][0]["cards"][0]["labels"] = []  # Deck always returns the field, empty when there is none
    out = RemoveLabelAction().execute(make_context(deck), {"label_id": 99})
    assert out["removed"] is False
    assert not [call for call in deck.calls if call[0] == "remove_label"]  # Deck would answer with an error


def test_remove_label_understands_labels_as_deck_returns_them_and_keeps_the_others():
    from automation.actions_registry.remove_label import RemoveLabelAction

    deck = make_deck()
    deck.stacks[1][0]["cards"][0]["labels"] = [{"id": 98, "title": "A"}, {"id": 99, "title": "B"}]
    RemoveLabelAction().execute(make_context(deck), {"label_id": 99})
    assert [e["id"] for e in deck.stacks[1][0]["cards"][0]["labels"]] == [98]


def test_remove_label_still_tries_when_the_card_cannot_be_read():
    from automation.actions_registry.remove_label import RemoveLabelAction

    deck = make_deck()
    deck.get_card = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("500"))
    out = RemoveLabelAction().execute(make_context(deck), {"label_id": 99})
    assert out["removed"] is True and ("remove_label", 1, 10, 100, 99) in deck.calls
