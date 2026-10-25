from __future__ import annotations

import sqlite3

import pytest

from automation.actions_registry.revoke_action_links import RevokeActionLinksAction
from automation.adapters.persistence.sqlite_state_store import SqliteStateStore
from automation.core.domain.models import DeckEvent, EventType
from automation.core.ports.action_module import ActionContext
from automation.testing.fakes import InMemoryActionLinkStore, InMemoryDeckGateway, InMemoryActionRegistry


def _event(card_id=7):
    return DeckEvent(instance="prod", board_id=1, event_type=EventType.CARD_CREATED, card_id=card_id, stack_id=10, card={"id": card_id})


def _make(store, workflow_id="wf1", event=None):
    return ActionContext(event=event or _event(), deck=InMemoryDeckGateway(), modules=InMemoryActionRegistry({}),
                         workflow_id=workflow_id, link_store=store)


def _link(store, workflow_id="wf1", card_id=7, **kw):
    return store.create_link(workflow_id=workflow_id, event=_event(card_id), current_stack_id=10, module="add_comment",
                             params={}, variables={}, success_message="ok", require_confirmation=False, **kw)


def test_revokes_only_this_workflows_links_of_this_card_by_default():
    store = InMemoryActionLinkStore()
    _link(store); _link(store); _link(store, workflow_id="other"); _link(store, card_id=8)
    out = RevokeActionLinksAction().execute(_make(store), {})
    assert out == {"revoked": 2}
    assert [bool(link.get("revoked")) for link in store.links] == [True, True, False, False]


def test_all_workflows_includes_the_other_workflows_links_of_the_card():
    store = InMemoryActionLinkStore()
    _link(store); _link(store, workflow_id="other"); _link(store, card_id=8)
    assert RevokeActionLinksAction().execute(_make(store), {"all_workflows": True}) == {"revoked": 2}


def test_without_a_link_store_the_step_fails_clearly():
    with pytest.raises(RuntimeError, match="link store"):
        RevokeActionLinksAction().execute(_make(None), {})


def test_sqlite_revokes_open_links_only_and_wipes_their_payload(tmp_path):
    db = tmp_path / "state.sqlite3"
    store = SqliteStateStore(db)
    kw = dict(workflow_id="wf", event=_event(), current_stack_id=10, module="add_comment", params={"message": "x"},
              variables={}, success_message="ok", require_confirmation=False)
    open_token, used_token, other_card = store.create_link(**kw), store.create_link(**kw), store.create_link(**{**kw, "event": _event(8)})
    import hashlib
    h = lambda t: hashlib.sha256(t.encode()).hexdigest()
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE action_links SET status = 'claimed' WHERE token_hash = ?", (h(used_token),))
    assert store.revoke_links(instance="prod", board_id=1, card_id=7, workflow_id="wf") == 1
    with sqlite3.connect(db) as conn:
        rows = dict(conn.execute("SELECT token_hash, status FROM action_links").fetchall())
        assert rows == {h(open_token): "revoked", h(used_token): "claimed", h(other_card): "open"}
        assert conn.execute("SELECT params_json FROM action_links WHERE token_hash = ?", (h(open_token),)).fetchone() == (None,)
    assert store.revoke_links(instance="prod", board_id=1, card_id=7) == 0  # nothing open any more
