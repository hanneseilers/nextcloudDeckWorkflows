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


def test_migrating_from_a_schema_without_run_id_or_module_does_not_crash(tmp_path):
    db_path = tmp_path / "state.sqlite3"
    # Simulate a pre-existing database from before these two columns existed.
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE execution_log (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "workflow_id TEXT NOT NULL, event_type TEXT NOT NULL, card_id INTEGER NOT NULL, "
            "success INTEGER NOT NULL, error TEXT, created_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO execution_log (workflow_id, event_type, card_id, success, error, created_at) "
            "VALUES ('wf-old', 'card_created', 1, 1, NULL, '2026-01-01T00:00:00+00:00')"
        )
        conn.commit()

    store = SqliteStateStore(db_path)  # must not raise

    event = DeckEvent(instance="inst", board_id=1, event_type=EventType.CARD_CREATED, card_id=1, stack_id=10)
    store.record(ExecutionResult(
        workflow_id="wf-new", event=event, action_results=[ActionResult(module="a", success=True)],
    ))

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT workflow_id, module, run_id FROM execution_log ORDER BY id").fetchall()
    assert rows[0] == ("wf-old", None, None)  # pre-existing row untouched
    assert rows[1][0] == "wf-new" and rows[1][1] == "a" and rows[1][2]


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
        rows = conn.execute(
            "SELECT workflow_id, module, success, error FROM execution_log ORDER BY id"
        ).fetchall()
    assert rows == [("wf-1", "a", 1, None), ("wf-1", "b", 0, "boom")]


def test_record_gives_every_row_of_one_run_the_same_run_id(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")
    event = DeckEvent(instance="inst", board_id=1, event_type=EventType.CARD_CREATED, card_id=1, stack_id=10)
    result = ExecutionResult(
        workflow_id="wf-1",
        event=event,
        action_results=[ActionResult(module="a", success=True), ActionResult(module="b", success=True)],
    )

    store.record(result)

    with sqlite3.connect(tmp_path / "state.sqlite3") as conn:
        run_ids = conn.execute("SELECT run_id FROM execution_log ORDER BY id").fetchall()
    assert run_ids[0] == run_ids[1]
    assert run_ids[0][0]  # non-empty


def test_record_gives_two_separate_calls_different_run_ids(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")
    event = DeckEvent(instance="inst", board_id=1, event_type=EventType.CARD_CREATED, card_id=1, stack_id=10)

    store.record(ExecutionResult(workflow_id="wf-1", event=event, action_results=[ActionResult(module="a", success=True)]))
    store.record(ExecutionResult(workflow_id="wf-1", event=event, action_results=[ActionResult(module="a", success=True)]))

    with sqlite3.connect(tmp_path / "state.sqlite3") as conn:
        run_ids = conn.execute("SELECT run_id FROM execution_log ORDER BY id").fetchall()
    assert run_ids[0] != run_ids[1]


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


def test_enqueue_test_run_shows_up_as_pending(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")

    test_run_id = store.enqueue_test_run("wf-1", 42)

    pending = store.pending_test_runs()
    assert pending == [{"id": test_run_id, "workflow_id": "wf-1", "card_id": 42}]


def test_complete_test_run_with_a_run_id_marks_it_done(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")
    test_run_id = store.enqueue_test_run("wf-1", 42)

    store.complete_test_run(test_run_id, run_id="run-abc")

    assert store.pending_test_runs() == []
    fetched = store.get_test_run(test_run_id)
    assert fetched["status"] == "done"
    assert fetched["run_id"] == "run-abc"
    assert fetched["error"] is None
    assert fetched["completed_at"] is not None


def test_complete_test_run_with_an_error_marks_it_error(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")
    test_run_id = store.enqueue_test_run("wf-1", 42)

    store.complete_test_run(test_run_id, error="Karte nicht gefunden")

    fetched = store.get_test_run(test_run_id)
    assert fetched["status"] == "error"
    assert fetched["error"] == "Karte nicht gefunden"
    assert fetched["run_id"] is None


def test_get_test_run_for_an_unknown_id_returns_none(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")

    assert store.get_test_run("does-not-exist") is None


def test_record_returns_the_run_id_it_generated(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")
    event = DeckEvent(instance="inst", board_id=1, event_type=EventType.CARD_CREATED, card_id=1, stack_id=10)

    run_id = store.record(ExecutionResult(
        workflow_id="wf-1", event=event, action_results=[ActionResult(module="a", success=True)],
    ))

    assert run_id
    with sqlite3.connect(tmp_path / "state.sqlite3") as conn:
        stored = conn.execute("SELECT run_id FROM execution_log").fetchone()
    assert stored[0] == run_id


def _record_run(store: SqliteStateStore, workflow_id: str, success: bool) -> None:
    event = DeckEvent(instance="inst", board_id=1, event_type=EventType.CARD_CREATED, card_id=1, stack_id=10)
    store.record(ExecutionResult(
        workflow_id=workflow_id, event=event,
        action_results=[ActionResult(module="a", success=success, error=None if success else "boom")],
    ))


def test_recent_run_outcomes_is_newest_first(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")
    _record_run(store, "wf-1", success=True)
    _record_run(store, "wf-1", success=False)
    _record_run(store, "wf-1", success=False)

    assert store.recent_run_outcomes("wf-1", limit=10) == [False, False, True]


def test_recent_run_outcomes_respects_the_limit(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")
    for _ in range(5):
        _record_run(store, "wf-1", success=False)

    assert len(store.recent_run_outcomes("wf-1", limit=2)) == 2


def test_failure_streak_notification_flag_roundtrip(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")

    assert store.has_notified_failure_streak("wf-1") is False

    store.mark_notified_failure_streak("wf-1")
    assert store.has_notified_failure_streak("wf-1") is True

    store.clear_notified_failure_streak("wf-1")
    assert store.has_notified_failure_streak("wf-1") is False


def test_set_heartbeat_is_readable_back_via_a_plain_query(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")

    store.set_heartbeat("2026-01-01T09:00:00+00:00")

    with sqlite3.connect(tmp_path / "state.sqlite3") as conn:
        row = conn.execute("SELECT last_run_at FROM heartbeat WHERE id = 1").fetchone()
    assert row[0] == "2026-01-01T09:00:00+00:00"


def test_set_heartbeat_overwrites_the_previous_value(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")
    store.set_heartbeat("2026-01-01T09:00:00+00:00")

    store.set_heartbeat("2026-01-02T09:00:00+00:00")

    with sqlite3.connect(tmp_path / "state.sqlite3") as conn:
        rows = conn.execute("SELECT last_run_at FROM heartbeat").fetchall()
    assert rows == [("2026-01-02T09:00:00+00:00",)]


def test_get_board_activity_defaults_to_both_none(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")

    assert store.get_board_activity("inst", 1) == (None, None)


def test_record_webhook_ping_and_poll_are_independent(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")

    store.record_webhook_ping("inst", 1, "2026-01-05T09:00:00+00:00")
    assert store.get_board_activity("inst", 1) == ("2026-01-05T09:00:00+00:00", None)

    store.record_poll("inst", 1, "2026-01-05T09:05:00+00:00")
    assert store.get_board_activity("inst", 1) == ("2026-01-05T09:00:00+00:00", "2026-01-05T09:05:00+00:00")


def test_board_activity_is_independent_per_board(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")

    store.record_webhook_ping("inst", 1, "2026-01-05T09:00:00+00:00")

    assert store.get_board_activity("inst", 2) == (None, None)
    assert store.get_board_activity("other-inst", 1) == (None, None)


def test_recent_webhook_pings_only_includes_boards_with_a_ping(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")
    store.record_poll("inst", 1, "2026-01-05T09:00:00+00:00")  # polled, never pinged
    store.record_webhook_ping("inst", 2, "2026-01-05T09:05:00+00:00")

    pings = store.recent_webhook_pings()

    assert pings == [{"instance": "inst", "board_id": 2, "last_ping_at": "2026-01-05T09:05:00+00:00"}]


def _link_event():
    return DeckEvent(instance="prod", board_id=1, event_type=EventType.CARD_MOVED, card_id=7, stack_id=10,
                     card={"id": 7, "title": "T"})


def _make_link(store, **overrides):
    kwargs = dict(workflow_id="wf", event=_link_event(), current_stack_id=20, module="add_comment",
                  params={"message": "hi"}, variables={"a": 1}, success_message="ok", require_confirmation=False)
    kwargs.update(overrides)
    return store.create_link(**kwargs)


def test_action_link_stores_only_the_hash_of_the_token(tmp_path):
    import hashlib

    store = SqliteStateStore(tmp_path / "state.sqlite3")
    token = _make_link(store)

    with sqlite3.connect(tmp_path / "state.sqlite3") as conn:
        stored = conn.execute("SELECT token_hash, status FROM action_links").fetchall()
    assert stored == [(hashlib.sha256(token.encode()).hexdigest(), "open")]
    assert token not in stored[0][0] and len(token) >= 40


def test_action_link_lifecycle_claimed_running_done_wipes_the_payload(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")
    _make_link(store)
    assert store.claimed_links() == []  # still "open" - nobody visited the page yet

    with sqlite3.connect(tmp_path / "state.sqlite3") as conn:  # what website/link.php does
        conn.execute("UPDATE action_links SET status = 'claimed', claimed_at = '2026-01-01T00:00:00+00:00'")

    [link] = store.claimed_links()
    assert (link["module"], link["params"], link["variables"], link["current_stack_id"]) == (
        "add_comment", {"message": "hi"}, {"a": 1}, 20)
    assert link["event_type"] == EventType.CARD_MOVED and link["card"] == {"id": 7, "title": "T"}

    assert store.begin_link_run(link["token_hash"]) is True
    assert store.begin_link_run(link["token_hash"]) is False  # a second run can't take it again
    store.finish_link(link["token_hash"], error="boom")

    with sqlite3.connect(tmp_path / "state.sqlite3") as conn:
        row = conn.execute("SELECT status, error, params_json, variables_json, card_json FROM action_links").fetchone()
    assert row == ("error", "boom", None, None, None)


def test_purge_removes_only_old_finished_links(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")
    _make_link(store)
    _make_link(store)
    with sqlite3.connect(tmp_path / "state.sqlite3") as conn:
        hashes = [r[0] for r in conn.execute("SELECT token_hash FROM action_links")]
    store.finish_link(hashes[0])

    store.purge_finished_links("2999-01-01T00:00:00+00:00")

    with sqlite3.connect(tmp_path / "state.sqlite3") as conn:
        assert [r[0] for r in conn.execute("SELECT token_hash FROM action_links")] == [hashes[1]]


def test_duplicate_guard_remembers_a_key_only_for_the_given_window(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")

    assert store.seen_within("k", 15) is False
    store.remember("k")
    assert store.seen_within("k", 15) is True
    assert store.seen_within("other", 15) is False

    with sqlite3.connect(tmp_path / "state.sqlite3") as conn:
        conn.execute("UPDATE dedupe_keys SET created_at = '2000-01-01T00:00:00+00:00'")
    assert store.seen_within("k", 15) is False  # long ago: outside the window


def test_history_indexes_exist_and_purge_drops_only_old_rows(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")
    event = DeckEvent(instance="i", board_id=1, event_type=EventType.CARD_CREATED, card_id=1, stack_id=10)
    store.record(ExecutionResult(workflow_id="w", event=event, action_results=[ActionResult(module="m", success=True)]))
    store.record(ExecutionResult(workflow_id="w", event=event, action_results=[ActionResult(module="m", success=True)]))
    with sqlite3.connect(tmp_path / "state.sqlite3") as conn:
        conn.execute("UPDATE execution_log SET created_at = '2000-01-01T00:00:00+00:00' WHERE id = 1")
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert {"execution_log_workflow", "execution_log_run", "execution_log_created"} <= names

    store.purge_history("2020-01-01T00:00:00+00:00")

    with sqlite3.connect(tmp_path / "state.sqlite3") as conn:
        assert [r[0] for r in conn.execute("SELECT id FROM execution_log")] == [2]


def test_indexes_are_created_on_a_legacy_database_without_run_id(tmp_path):
    db = tmp_path / "state.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE execution_log (id INTEGER PRIMARY KEY AUTOINCREMENT, workflow_id TEXT NOT NULL, "
                     "event_type TEXT NOT NULL, card_id INTEGER NOT NULL, success INTEGER NOT NULL, error TEXT, "
                     "created_at TEXT NOT NULL)")
    SqliteStateStore(db)  # must migrate (add run_id) before indexing it
    with sqlite3.connect(db) as conn:
        assert "run_id" in [r[1] for r in conn.execute("PRAGMA table_info(execution_log)")]


def test_copy_store_roundtrip(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")
    assert store.copy_info("i", 1, 5) is None
    store.record_copy("i", 1, 5, "wf", 2)
    assert store.copy_info("i", 1, 5) == ("wf", 2)
