from __future__ import annotations

import pytest

from automation.actions_registry.assign_user import AssignUserAction
from automation.actions_registry.unassign_user import UnassignUserAction
from automation.adapters.actions.user_ids import parse_user_ids
from automation.core.domain.card_data import assigned_user_ids
from automation.tests.test_actions import make_context, make_deck


def assigned(deck):
    return [e["participant"]["uid"] for e in deck.stacks[1][0]["cards"][0].get("assignedUsers", [])]


def calls(deck, name):
    return [c[4] for c in deck.calls if c[0] == name]


# -- parsing -------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("anna", ["anna"]),
    ("anna, bernd;carla\ndora", ["anna", "bernd", "carla", "dora"]),
    ("anna maier", ["anna maier"]),  # Nextcloud ids may contain spaces
    (["anna", " bernd ", "anna", ""], ["anna", "bernd"]),
    (["anna,bernd", "carla"], ["anna", "bernd", "carla"]),
    ("", []), (None, []), (7, []), ([None, 5], []),
])
def test_parse_user_ids(value, expected):
    assert parse_user_ids(value) == expected


def test_assigned_user_ids_reads_the_known_shapes_in_order_without_duplicates():
    card = {"assignedUsers": [
        {"participant": {"uid": "anna"}}, {"uid": "bernd"}, {"id": 7}, {"participant": {"uid": "anna"}}, "junk", {},
    ]}
    assert assigned_user_ids(card) == ["anna", "bernd", "7"]
    assert assigned_user_ids({}) == [] and assigned_user_ids(None) == []


# -- assign ----------------------------------------------------------------------

def test_assign_several_users_at_once_as_a_list_or_comma_separated():
    deck = make_deck()
    out = AssignUserAction().execute(make_context(deck), {"user_id": ["anna", "bernd"]})
    assert assigned(deck) == ["anna", "bernd"] and out == {"user_ids": ["anna", "bernd"]}

    deck = make_deck()
    AssignUserAction().execute(make_context(deck), {"user_id": "anna, bernd"})
    assert assigned(deck) == ["anna", "bernd"]


def test_assign_a_single_user_still_works_as_before():
    deck = make_deck()
    AssignUserAction().execute(make_context(deck), {"user_id": "alice"})
    assert assigned(deck) == ["alice"]


def test_assign_skips_users_who_are_already_assigned():
    deck = make_deck()
    context = make_context(deck)
    AssignUserAction().execute(context, {"user_id": "anna"})
    AssignUserAction().execute(context, {"user_id": ["anna", "bernd"]})
    assert calls(deck, "assign_user") == ["anna", "bernd"]  # anna only once - Deck would refuse the second
    AssignUserAction().execute(context, {"user_id": ["anna", "bernd"]})
    assert calls(deck, "assign_user") == ["anna", "bernd"]  # running it again changes nothing


def test_assign_without_a_user_fails_clearly():
    with pytest.raises(ValueError):
        AssignUserAction().execute(make_context(make_deck()), {"user_id": ""})


def test_assign_continues_after_one_user_fails_and_then_reports_it():
    deck = make_deck()
    original = deck.assign_user

    def flaky(board_id, stack_id, card_id, user_id):
        if user_id == "kaputt":
            raise RuntimeError("404 no such user")
        original(board_id, stack_id, card_id, user_id)

    deck.assign_user = flaky
    with pytest.raises(RuntimeError, match="kaputt: 404"):
        AssignUserAction().execute(make_context(deck), {"user_id": ["anna", "kaputt", "bernd"]})
    assert assigned(deck) == ["anna", "bernd"]


def test_assign_still_tries_every_user_when_the_card_cannot_be_read():
    deck = make_deck()
    deck.get_card = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("500"))
    AssignUserAction().execute(make_context(deck), {"user_id": ["anna", "bernd"]})
    assert assigned(deck) == ["anna", "bernd"]


# -- unassign --------------------------------------------------------------------

def test_unassign_several_users():
    deck = make_deck()
    context = make_context(deck)
    AssignUserAction().execute(context, {"user_id": ["anna", "bernd", "carla"]})
    out = UnassignUserAction().execute(context, {"user_id": "anna, carla"})
    assert assigned(deck) == ["bernd"] and out == {"user_ids": ["anna", "carla"]}


def test_unassign_everybody():
    deck = make_deck()
    context = make_context(deck)
    AssignUserAction().execute(context, {"user_id": ["anna", "bernd", "carla"]})
    out = UnassignUserAction().execute(context, {"user_id": "ignored", "all_users": True})
    assert assigned(deck) == [] and out == {"user_ids": ["anna", "bernd", "carla"]}
    assert "ignored" not in calls(deck, "unassign_user")


def test_unassign_everybody_on_a_card_nobody_is_assigned_to_is_fine():
    deck = make_deck()
    out = UnassignUserAction().execute(make_context(deck), {"all_users": True})
    assert out == {"user_ids": []} and calls(deck, "unassign_user") == []


def test_unassign_skips_users_who_are_not_assigned():
    deck = make_deck()
    context = make_context(deck)
    AssignUserAction().execute(context, {"user_id": "anna"})
    out = UnassignUserAction().execute(context, {"user_id": ["anna", "nie-zugewiesen"]})
    assert calls(deck, "unassign_user") == ["anna"] and out == {"user_ids": ["anna"]}


def test_unassign_without_a_user_and_without_all_fails_clearly():
    with pytest.raises(ValueError):
        UnassignUserAction().execute(make_context(make_deck()), {"user_id": "", "all_users": False})


def test_unassign_all_fails_when_the_card_cannot_be_read():
    deck = make_deck()
    deck.get_card = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("500"))
    with pytest.raises(RuntimeError, match="who is assigned"):
        UnassignUserAction().execute(make_context(deck), {"all_users": True})


def test_unassign_named_users_are_tried_when_the_assignees_cannot_be_read():
    deck = make_deck()
    context = make_context(deck)
    AssignUserAction().execute(context, {"user_id": "anna"})
    deck.get_card = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("500"))
    UnassignUserAction().execute(context, {"user_id": "anna"})
    assert assigned(deck) == []


def test_unassign_continues_after_a_failure_and_reports_it():
    deck = make_deck()
    context = make_context(deck)
    AssignUserAction().execute(context, {"user_id": ["anna", "bernd", "carla"]})
    original = deck.unassign_user

    def flaky(board_id, stack_id, card_id, user_id):
        if user_id == "bernd":
            raise RuntimeError("500")
        original(board_id, stack_id, card_id, user_id)

    deck.unassign_user = flaky
    with pytest.raises(RuntimeError, match="bernd"):
        UnassignUserAction().execute(context, {"all_users": True})
    assert assigned(deck) == ["bernd"]
