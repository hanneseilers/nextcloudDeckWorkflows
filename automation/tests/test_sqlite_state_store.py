from __future__ import annotations

import sqlite3

from automation.adapters.persistence.sqlite_state_store import SqliteStateStore
from automation.core.domain.models import ActionResult, DeckEvent, EventType, ExecutionResult


def test_save_and_load_roundtrip_including_extra_fields(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")

    store.save("inst", 1, {
        100: {"stack_id": 10, "last_modified": 5, "duedate": "2026-01-01", "assignee_ids": ["alice"]},
    })

    loaded = store.load("inst", 1)

    assert loaded == {
        100: {"stack_id": 10, "last_modified": 5, "duedate": "2026-01-01", "assignee_ids": ["alice"]},
    }


def test_load_with_no_snapshot_yet_returns_empty_dict(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")

    assert store.load("inst", 1) == {}


def test_save_overwrites_the_previous_snapshot_for_that_board(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")
    store.save("inst", 1, {100: {"stack_id": 10, "last_modified": 1}})

    store.save("inst", 1, {200: {"stack_id": 20, "last_modified": 2}})

    assert store.load("inst", 1) == {200: {"stack_id": 20, "last_modified": 2}}


def test_migrating_from_a_schema_without_the_extra_column_does_not_crash(tmp_path):
    db_path = tmp_path / "state.sqlite3"
    # Simulate a pre-existing database from before the "extra" column existed.
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE board_snapshots ("
            "instance TEXT NOT NULL, board_id INTEGER NOT NULL, card_id INTEGER NOT NULL, "
            "stack_id INTEGER NOT NULL, last_modified INTEGER NOT NULL, "
            "PRIMARY KEY (instance, board_id, card_id))"
        )
        conn.execute(
            "INSERT INTO board_snapshots VALUES ('inst', 1, 100, 10, 5)"
        )
        conn.commit()

    store = SqliteStateStore(db_path)

    assert store.load("inst", 1) == {100: {"stack_id": 10, "last_modified": 5}}


def test_record_writes_one_row_per_action_result(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")
    event = DeckEvent(instance="inst", board_id=1, event_type=EventType.CARD_CREATED, card_id=1, stack_id=10)
    result = ExecutionResult(
        workflow_id="wf-1",
        event=event,
        action_results=[
            ActionResult(module="a", success=True),
            ActionResult(module="b", success=False, error="boom"),
        ],
    )

    store.record(result)

    with sqlite3.connect(tmp_path / "state.sqlite3") as conn:
        rows = conn.execute("SELECT workflow_id, success, error FROM execution_log ORDER BY id").fetchall()
    assert rows == [("wf-1", 1, None), ("wf-1", 0, "boom")]


def test_add_number_then_contains_number_finds_it(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")

    assert store.contains_number("tickets", "0042") is False

    store.add_number("tickets", "0042")

    assert store.contains_number("tickets", "0042") is True


def test_number_lists_are_independent_by_list_name(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")
    store.add_number("tickets", "0042")

    assert store.contains_number("other-list", "0042") is False


def test_add_number_is_idempotent(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")

    store.add_number("tickets", "0042")
    store.add_number("tickets", "0042")  # must not raise (duplicate primary key)

    assert store.contains_number("tickets", "0042") is True


def test_remove_number_makes_it_available_again(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")
    store.add_number("tickets", "0042")

    store.remove_number("tickets", "0042")

    assert store.contains_number("tickets", "0042") is False


def test_remove_number_that_was_never_added_does_not_raise(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")

    store.remove_number("tickets", "does-not-exist")  # no-op, no exception
