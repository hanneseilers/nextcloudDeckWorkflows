from __future__ import annotations

import pytest

from automation.actions_registry.create_action_link import DEFAULT_SUCCESS_MESSAGE, CreateActionLinkAction
from automation.core.domain.models import DeckEvent, EventType
from automation.core.ports.action_module import ActionContext
from automation.testing.fakes import InMemoryActionLinkStore, InMemoryActionRegistry, InMemoryDeckGateway


class _Noop:
    ACTION_NAME = "add_comment"


def make(store, public_url="https://x.example/site", variables=None):
    event = DeckEvent(instance="prod", board_id=1, event_type=EventType.CARD_CREATED, card_id=7, stack_id=10,
                      card={"id": 7, "title": "T"})
    ctx = ActionContext(
        event=event, deck=InMemoryDeckGateway(), modules=InMemoryActionRegistry({"add_comment": _Noop()}),
        variables=variables or {}, workflow_id="wf1", link_store=store, public_url=public_url,
    )
    ctx.current_stack_id = 20
    return ctx


def test_creates_a_link_with_the_current_card_context_and_returns_its_url():
    store = InMemoryActionLinkStore()
    out = CreateActionLinkAction().execute(
        make(store, variables={"nr": "0042"}),
        {"action": "add_comment", "action_params": {"message": "hi"}, "success_message": "Danke!"},
    )

    assert out == {"url": "https://x.example/site/link.php?h=token1", "expires_at": None, "expires_text": "unbegrenzt"}
    link = store.links[0]
    assert link["workflow_id"] == "wf1" and link["module"] == "add_comment"
    assert link["params"] == {"message": "hi"} and link["variables"] == {"nr": "0042"}
    assert link["event"].card_id == 7 and link["current_stack_id"] == 20
    assert link["success_message"] == "Danke!" and link["require_confirmation"] is False


def test_empty_success_message_falls_back_to_the_default_text():
    store = InMemoryActionLinkStore()
    CreateActionLinkAction().execute(make(store), {"action": "add_comment", "success_message": "  "})
    assert store.links[0]["success_message"] == DEFAULT_SUCCESS_MESSAGE


@pytest.mark.parametrize("params,exc", [
    ({"action": ""}, ValueError),
    ({"action": "create_action_link"}, ValueError),
    ({"action": "nope"}, KeyError),
    ({"action": "add_comment", "action_params": "text"}, ValueError),
])
def test_invalid_params_are_rejected_at_creation_time(params, exc):
    with pytest.raises(exc):
        CreateActionLinkAction().execute(make(InMemoryActionLinkStore()), params)


def test_requires_public_url_and_link_store():
    with pytest.raises(ValueError, match="public_url"):
        CreateActionLinkAction().execute(make(InMemoryActionLinkStore(), public_url=None), {"action": "add_comment"})
    with pytest.raises(RuntimeError):
        CreateActionLinkAction().execute(make(None), {"action": "add_comment"})


def test_valid_days_sets_an_expiry_and_returns_it_for_texts():
    from datetime import datetime, timedelta, timezone

    store = InMemoryActionLinkStore()
    ctx = make(store)
    ctx.display_timezone = "Europe/Berlin"
    before = datetime.now(timezone.utc)
    out = CreateActionLinkAction().execute(ctx, {"action": "add_comment", "valid_days": 3})

    expires = datetime.fromisoformat(out["expires_at"])
    assert timedelta(days=3) - timedelta(seconds=5) < expires - before < timedelta(days=3, seconds=5)
    assert store.links[0]["expires_at"] == out["expires_at"]
    from zoneinfo import ZoneInfo
    assert out["expires_text"] == expires.astimezone(ZoneInfo("Europe/Berlin")).strftime("%d.%m.%Y %H:%M")


@pytest.mark.parametrize("days", [0, None, ""])
def test_zero_or_empty_valid_days_means_no_expiry(days):
    store = InMemoryActionLinkStore()
    out = CreateActionLinkAction().execute(make(store), {"action": "add_comment", "valid_days": days})
    assert out["expires_at"] is None and store.links[0]["expires_at"] is None


def test_negative_valid_days_is_rejected():
    with pytest.raises(ValueError):
        CreateActionLinkAction().execute(make(InMemoryActionLinkStore()), {"action": "add_comment", "valid_days": -1})


def test_unknown_timezone_falls_back_to_utc_text():
    ctx = make(InMemoryActionLinkStore())
    ctx.display_timezone = "Nowhere/Nothing"
    out = CreateActionLinkAction().execute(ctx, {"action": "add_comment", "valid_days": 1})
    assert out["expires_text"].endswith(" UTC")


# -- up to three actions per link ---------------------------------------------------------------

def make_with(store, *names):
    ctx = make(store)
    ctx.modules = InMemoryActionRegistry({name: _Noop() for name in names})
    return ctx


def test_a_link_can_run_up_to_three_actions_in_order():
    store = InMemoryActionLinkStore()
    CreateActionLinkAction().execute(make_with(store, "add_comment", "move_card", "assign_user"), {
        "action": "add_comment", "action_params": {"message": "hi"},
        "action_2": "move_card", "action_params_2": {"target_stack_id": 30},
        "action_3": "assign_user", "action_params_3": {"user_id": "anna"},
    })
    link = store.links[0]
    assert (link["module"], link["params"]) == ("add_comment", {"message": "hi"})  # the first one, as before
    assert link["extra_steps"] == [
        {"module": "move_card", "params": {"target_stack_id": 30}},
        {"module": "assign_user", "params": {"user_id": "anna"}},
    ]


def test_a_link_with_one_action_has_no_extra_steps():
    store = InMemoryActionLinkStore()
    CreateActionLinkAction().execute(make_with(store, "add_comment"), {"action": "add_comment", "action_params": {}})
    assert store.links[0]["extra_steps"] == []


def test_an_empty_second_action_is_skipped_and_the_third_moves_up():
    store = InMemoryActionLinkStore()
    CreateActionLinkAction().execute(make_with(store, "add_comment", "move_card"), {
        "action": "add_comment", "action_2": "", "action_params_2": {"x": 1}, "action_3": "move_card", "action_params_3": {"target_stack_id": 5},
    })
    assert store.links[0]["extra_steps"] == [{"module": "move_card", "params": {"target_stack_id": 5}}]


@pytest.mark.parametrize("params, message", [
    ({"action": "add_comment", "action_2": "create_action_link"}, "cannot run create_action_link"),
    ({"action": "add_comment", "action_3": "create_action_link"}, "cannot run create_action_link"),
    ({"action": "add_comment", "action_2": "gibtsnicht"}, None),                                  # unknown: fails at creation, not on click
    ({"action": "add_comment", "action_2": "add_comment", "action_params_2": "nope"}, "action_params_2"),
    ({"action": "", "action_2": "add_comment"}, "`action` is required"),                           # the first one is not optional
])
def test_every_action_of_a_link_is_checked_when_the_link_is_created(params, message):
    store = InMemoryActionLinkStore()
    with pytest.raises(Exception) as caught:
        CreateActionLinkAction().execute(make(store), params)
    if message:
        assert message in str(caught.value)
    assert store.links == []  # nothing half-created


def test_a_workflow_saved_before_the_extra_actions_existed_still_works():
    store = InMemoryActionLinkStore()
    CreateActionLinkAction().execute(make(store), {"action": "add_comment", "action_params": {"message": "alt"}})
    assert store.links[0]["extra_steps"] == [] and store.links[0]["params"] == {"message": "alt"}
