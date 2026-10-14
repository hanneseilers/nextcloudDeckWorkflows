from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from automation.core.domain.models import ExecutionResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS board_snapshots (
    instance TEXT NOT NULL,
    board_id INTEGER NOT NULL,
    card_id INTEGER NOT NULL,
    stack_id INTEGER NOT NULL,
    last_modified INTEGER NOT NULL,
    PRIMARY KEY (instance, board_id, card_id)
);

CREATE TABLE IF NOT EXISTS execution_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    card_id INTEGER NOT NULL,
    success INTEGER NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS used_numbers (
    list_name TEXT NOT NULL,
    value TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (list_name, value)
);

CREATE TABLE IF NOT EXISTS schedule_state (
    workflow_id TEXT PRIMARY KEY,
    last_fired_at TEXT NOT NULL
);

-- Presence of a row means "already notified for the current, still
-- unbroken consecutive-failure streak" - see main.py::_process_failure_notifications.
CREATE TABLE IF NOT EXISTS failure_notifications (
    workflow_id TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS test_runs (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    card_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    run_id TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
"""

# Added after the fact (see _SCHEMA above) via ALTER TABLE so an existing
# state.sqlite3 from before this field existed keeps working - CREATE TABLE
# IF NOT EXISTS alone wouldn't add it to an already-existing table.
_EXTRA_COLUMN = "extra"
# Same migration-safe story for execution_log: run_id groups every action's
# row from the same record() call (the website's history view needs this to
# reconstruct "these N rows were one workflow run", which a shared but
# separately-computed timestamp per row couldn't guarantee); module names
# which action each row is actually about, previously only inferable from
# position.
_RUN_ID_COLUMN = "run_id"
_MODULE_COLUMN = "module"


class SqliteStateStore:
    """Implements SnapshotStorePort (board diffing state), ExecutionLogPort
    (workflow run history) and SequenceStorePort (generate_random_number's
    "already generated" lists). SQLite instead of YAML because this is
    machine-written, frequently updated runtime data with no need for manual
    editing - unlike the workflow definitions themselves.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.executescript(_SCHEMA)
            for table, column, col_type in [
                ("board_snapshots", _EXTRA_COLUMN, "TEXT"),
                ("execution_log", _RUN_ID_COLUMN, "TEXT"),
                ("execution_log", _MODULE_COLUMN, "TEXT"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                except sqlite3.OperationalError:
                    pass  # column already exists (or table was just created with it - either is fine)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    # -- SnapshotStorePort ----------------------------------------------------

    def load(self, instance: str, board_id: int) -> dict[int, dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT card_id, stack_id, last_modified, {_EXTRA_COLUMN} FROM board_snapshots "
                "WHERE instance = ? AND board_id = ?",
                (instance, board_id),
            ).fetchall()
        result: dict[int, dict[str, Any]] = {}
        for card_id, stack_id, last_modified, extra_json in rows:
            extra = json.loads(extra_json) if extra_json else {}
            result[card_id] = {"stack_id": stack_id, "last_modified": last_modified, **extra}
        return result

    def save(self, instance: str, board_id: int, snapshot: dict[int, dict[str, Any]]) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "DELETE FROM board_snapshots WHERE instance = ? AND board_id = ?",
                (instance, board_id),
            )
            conn.executemany(
                f"INSERT INTO board_snapshots (instance, board_id, card_id, stack_id, last_modified, {_EXTRA_COLUMN}) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        instance,
                        board_id,
                        card_id,
                        state["stack_id"],
                        state["last_modified"],
                        json.dumps({k: v for k, v in state.items() if k not in ("stack_id", "last_modified")}),
                    )
                    for card_id, state in snapshot.items()
                ],
            )
            conn.commit()

    # -- ExecutionLogPort -------------------------------------------------------

    def record(self, result: ExecutionResult) -> str:
        # One id and one timestamp for the whole run (not recomputed per
        # action_result) - the website's history view groups rows back into
        # "one run" by run_id, which only works if every row of that run
        # actually shares the same value.
        run_id = uuid.uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as conn:
            for action_result in result.action_results:
                conn.execute(
                    "INSERT INTO execution_log "
                    f"({_RUN_ID_COLUMN}, workflow_id, event_type, card_id, {_MODULE_COLUMN}, "
                    "success, error, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        result.workflow_id,
                        result.event.event_type.value,
                        result.event.card_id,
                        action_result.module,
                        int(action_result.success),
                        action_result.error,
                        created_at,
                    ),
                )
            conn.commit()
        return run_id

    # -- SequenceStorePort ------------------------------------------------------

    def contains_number(self, list_name: str, value: str) -> bool:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT 1 FROM used_numbers WHERE list_name = ? AND value = ?", (list_name, value)
            ).fetchone()
        return row is not None

    def add_number(self, list_name: str, value: str) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO used_numbers (list_name, value, created_at) VALUES (?, ?, ?)",
                (list_name, value, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()

    def remove_number(self, list_name: str, value: str) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "DELETE FROM used_numbers WHERE list_name = ? AND value = ?", (list_name, value)
            )
            conn.commit()

    # -- TestRunQueuePort ---------------------------------------------------------
    # Backs the website's "Testlauf" button: the website (a separate PHP
    # process, which never executes Python itself) writes a pending request
    # here; main.py's run() picks it up on its next invocation (manual or
    # cron) and records the real result back - the same "write a request,
    # the background process picks it up" shape workflows/*.yaml already
    # uses, just for a one-off run instead of a standing definition.

    def enqueue_test_run(self, workflow_id: str, card_id: int) -> str:
        test_run_id = uuid.uuid4().hex
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO test_runs (id, workflow_id, card_id, status, created_at) "
                "VALUES (?, ?, ?, 'pending', ?)",
                (test_run_id, workflow_id, card_id, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        return test_run_id

    def pending_test_runs(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT id, workflow_id, card_id FROM test_runs WHERE status = 'pending' ORDER BY created_at"
            ).fetchall()
        return [{"id": row[0], "workflow_id": row[1], "card_id": row[2]} for row in rows]

    def complete_test_run(
        self, test_run_id: str, *, run_id: Optional[str] = None, error: Optional[str] = None
    ) -> None:
        status = "error" if error else "done"
        with closing(self._connect()) as conn:
            conn.execute(
                "UPDATE test_runs SET status = ?, run_id = ?, error = ?, completed_at = ? WHERE id = ?",
                (status, run_id, error, datetime.now(timezone.utc).isoformat(), test_run_id),
            )
            conn.commit()

    def get_test_run(self, test_run_id: str) -> Optional[dict[str, Any]]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT id, workflow_id, card_id, status, run_id, error, created_at, completed_at "
                "FROM test_runs WHERE id = ?",
                (test_run_id,),
            ).fetchone()
        if row is None:
            return None
        keys = ("id", "workflow_id", "card_id", "status", "run_id", "error", "created_at", "completed_at")
        return dict(zip(keys, row))

    # -- ScheduleStatePort --------------------------------------------------------

    def get_last_fired(self, workflow_id: str) -> Optional[str]:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT last_fired_at FROM schedule_state WHERE workflow_id = ?", (workflow_id,)
            ).fetchone()
        return row[0] if row else None

    def set_last_fired(self, workflow_id: str, when_iso: str) -> None:
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO schedule_state (workflow_id, last_fired_at) VALUES (?, ?) "
                "ON CONFLICT(workflow_id) DO UPDATE SET last_fired_at = excluded.last_fired_at",
                (workflow_id, when_iso),
            )
            conn.commit()

    # -- failure notifications ----------------------------------------------------

    def recent_run_outcomes(self, workflow_id: str, limit: int) -> list[bool]:
        """Newest-run-first list of whether each of this workflow's most
        recent runs (grouped by run_id - MIN(success) is 0/False if any
        action in that run failed) fully succeeded."""

        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT MIN(success) FROM execution_log WHERE workflow_id = ? AND run_id IS NOT NULL "
                "GROUP BY run_id ORDER BY MAX(id) DESC LIMIT ?",
                (workflow_id, limit),
            ).fetchall()
        return [bool(row[0]) for row in rows]

    def has_notified_failure_streak(self, workflow_id: str) -> bool:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT 1 FROM failure_notifications WHERE workflow_id = ?", (workflow_id,)
            ).fetchone()
        return row is not None

    def mark_notified_failure_streak(self, workflow_id: str) -> None:
        with closing(self._connect()) as conn:
            conn.execute("INSERT OR IGNORE INTO failure_notifications (workflow_id) VALUES (?)", (workflow_id,))
            conn.commit()

    def clear_notified_failure_streak(self, workflow_id: str) -> None:
        with closing(self._connect()) as conn:
            conn.execute("DELETE FROM failure_notifications WHERE workflow_id = ?", (workflow_id,))
            conn.commit()
