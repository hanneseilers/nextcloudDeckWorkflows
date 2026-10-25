from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from automation.core.domain.models import DeckEvent, EventType, ExecutionResult

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

-- Single row (id=1): when main.py's run() last completed without an
-- unhandled exception - the website's health check reads this to answer
-- "is the cron job actually still running".
CREATE TABLE IF NOT EXISTS heartbeat (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_run_at TEXT NOT NULL
);

-- One row per board ever seen by the webhook/polling-gate logic (see
-- core/domain/webhook_gate.py) - last_ping_at is written by
-- website/webhook.php, last_polled_at by main.py itself.
CREATE TABLE IF NOT EXISTS board_activity (
    instance TEXT NOT NULL,
    board_id INTEGER NOT NULL,
    last_ping_at TEXT,
    last_polled_at TEXT,
    PRIMARY KEY (instance, board_id)
);

-- One-time action links (create_action_link). Only the SHA-256 of the
-- secret token is stored. status: open -> claimed (website/link.php, atomic)
-- -> running -> done|error (main.py); the payload columns are wiped once
-- the link has been used.
CREATE TABLE IF NOT EXISTS action_links (
    token_hash TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    instance TEXT,
    board_id INTEGER,
    card_id INTEGER,
    stack_id INTEGER,
    current_stack_id INTEGER,
    event_type TEXT,
    card_json TEXT,
    module TEXT,
    params_json TEXT,
    variables_json TEXT,
    extra_steps_json TEXT,
    confirm_message TEXT NOT NULL DEFAULT '',
    success_message TEXT NOT NULL DEFAULT '',
    require_confirmation INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    claimed_at TEXT,
    running_at TEXT,
    finished_at TEXT,
    expires_at TEXT
);

-- Cards copy_card created (CopyStorePort): which workflow, how deep a copy.
CREATE TABLE IF NOT EXISTS copied_cards (
    instance TEXT NOT NULL,
    board_id INTEGER NOT NULL,
    card_id INTEGER NOT NULL,
    workflow_id TEXT NOT NULL,
    depth INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (instance, board_id, card_id)
);

-- "Already done recently" memory (DuplicateGuardPort) - e.g. an email sent.
CREATE TABLE IF NOT EXISTS dedupe_keys (
    key TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS test_runs (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    card_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    run_id TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    started_at TEXT
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


_INSERT_SNAPSHOT_ROW = (
    f"INSERT INTO board_snapshots (instance, board_id, card_id, stack_id, last_modified, {_EXTRA_COLUMN}) "
    "VALUES (?, ?, ?, ?, ?, ?)"
)


def _snapshot_row(instance: str, board_id: int, card_id: int, state: dict[str, Any]) -> tuple:
    return (
        instance,
        board_id,
        card_id,
        state["stack_id"],
        state["last_modified"],
        json.dumps({k: v for k, v in state.items() if k not in ("stack_id", "last_modified")}),
    )


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
        # One connection held open for this store's whole lifetime (a single,
        # short-lived cron invocation calls dozens of these methods per run -
        # per board, per action, per test run - so reopening/closing a file
        # connection on every single call was pure overhead) instead of a
        # fresh sqlite3.connect()/close() per method call.
        self._conn: Optional[sqlite3.Connection] = None
        conn = self._connect()
        conn.executescript(_SCHEMA)
        for table, column, col_type in [
            ("board_snapshots", _EXTRA_COLUMN, "TEXT"),
            ("execution_log", _RUN_ID_COLUMN, "TEXT"),
            ("execution_log", _MODULE_COLUMN, "TEXT"),
            ("action_links", "running_at", "TEXT"),
            ("action_links", "expires_at", "TEXT"),
            # A link may run up to five actions: `module`/`params_json` hold the first,
            # this the others ([{"module": ..., "params": {...}}]); NULL on links created before.
            ("action_links", "extra_steps_json", "TEXT"),
            ("action_links", "confirm_message", "TEXT NOT NULL DEFAULT ''"),
            ("test_runs", "started_at", "TEXT"),
        ]:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            except sqlite3.OperationalError:
                pass  # column already exists (or table was just created with it - either is fine)
        # After the migrations above: run_id may only exist from here on.
        # execution_log grows with every run; the history/health pages and
        # the failure-notification check filter it by these columns.
        conn.executescript(
            "CREATE INDEX IF NOT EXISTS execution_log_workflow ON execution_log (workflow_id, id);"
            "CREATE INDEX IF NOT EXISTS execution_log_run ON execution_log (run_id);"
            "CREATE INDEX IF NOT EXISTS execution_log_created ON execution_log (created_at);"
        )
        conn.commit()

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path)
        return self._conn

    def close(self) -> None:
        """Not called by main.py (the process exits right after run()
        anyway) - provided for tests/long-lived callers that want to
        release the file handle explicitly instead of relying on process
        exit or garbage collection."""

        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # -- SnapshotStorePort ----------------------------------------------------

    def load(self, instance: str, board_id: int) -> dict[int, dict[str, Any]]:
        conn = self._connect()
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
        conn = self._connect()
        conn.execute(
            "DELETE FROM board_snapshots WHERE instance = ? AND board_id = ?",
            (instance, board_id),
        )
        conn.executemany(
            _INSERT_SNAPSHOT_ROW,
            [_snapshot_row(instance, board_id, card_id, state) for card_id, state in snapshot.items()],
        )
        conn.commit()

    def save_card(self, instance: str, board_id: int, card_id: int, state: Optional[dict[str, Any]]) -> None:
        conn = self._connect()
        conn.execute(
            "DELETE FROM board_snapshots WHERE instance = ? AND board_id = ? AND card_id = ?",
            (instance, board_id, card_id),
        )
        if state is not None:
            conn.execute(_INSERT_SNAPSHOT_ROW, _snapshot_row(instance, board_id, card_id, state))
        conn.commit()

    # -- ExecutionLogPort -------------------------------------------------------

    def record(self, result: ExecutionResult) -> str:
        # One id and one timestamp for the whole run (not recomputed per
        # action_result) - the website's history view groups rows back into
        # "one run" by run_id, which only works if every row of that run
        # actually shares the same value.
        run_id = uuid.uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
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
        conn = self._connect()
        row = conn.execute(
            "SELECT 1 FROM used_numbers WHERE list_name = ? AND value = ?", (list_name, value)
        ).fetchone()
        return row is not None

    def add_number(self, list_name: str, value: str) -> None:
        conn = self._connect()
        conn.execute(
            "INSERT OR IGNORE INTO used_numbers (list_name, value, created_at) VALUES (?, ?, ?)",
            (list_name, value, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()

    def remove_number(self, list_name: str, value: str) -> None:
        conn = self._connect()
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
        conn = self._connect()
        conn.execute(
            "INSERT INTO test_runs (id, workflow_id, card_id, status, created_at) "
            "VALUES (?, ?, ?, 'pending', ?)",
            (test_run_id, workflow_id, card_id, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return test_run_id

    def pending_test_runs(self) -> list[dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT id, workflow_id, card_id FROM test_runs WHERE status = 'pending' ORDER BY created_at"
        ).fetchall()
        return [{"id": row[0], "workflow_id": row[1], "card_id": row[2]} for row in rows]

    def claim_test_run(self, test_run_id: str) -> bool:
        """Atomically takes a pending test run for running - False if another
        process (the cron run, or the immediate run the website started) got
        it first, so a test run never executes twice."""

        conn = self._connect()
        cursor = conn.execute(
            "UPDATE test_runs SET status = 'running', started_at = ? WHERE id = ? AND status = 'pending'",
            (datetime.now(timezone.utc).isoformat(), test_run_id),
        )
        conn.commit()
        return cursor.rowcount == 1

    def fail_stale_test_runs(self, started_before_iso: str, error: str) -> None:
        """Test runs left 'running' by a killed process end as failed (not rerun - their actions may have happened)."""

        conn = self._connect()
        conn.execute(
            "UPDATE test_runs SET status = 'error', error = ?, completed_at = ? "
            "WHERE status = 'running' AND started_at < ?",
            (error, datetime.now(timezone.utc).isoformat(), started_before_iso),
        )
        conn.commit()

    def complete_test_run(
        self, test_run_id: str, *, run_id: Optional[str] = None, error: Optional[str] = None
    ) -> None:
        status = "error" if error else "done"
        conn = self._connect()
        conn.execute(
            "UPDATE test_runs SET status = ?, run_id = ?, error = ?, completed_at = ? WHERE id = ?",
            (status, run_id, error, datetime.now(timezone.utc).isoformat(), test_run_id),
        )
        conn.commit()

    def get_test_run(self, test_run_id: str) -> Optional[dict[str, Any]]:
        conn = self._connect()
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
        conn = self._connect()
        row = conn.execute(
            "SELECT last_fired_at FROM schedule_state WHERE workflow_id = ?", (workflow_id,)
        ).fetchone()
        return row[0] if row else None

    def set_last_fired(self, workflow_id: str, when_iso: str) -> None:
        conn = self._connect()
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

        conn = self._connect()
        rows = conn.execute(
            "SELECT MIN(success) FROM execution_log WHERE workflow_id = ? AND run_id IS NOT NULL "
            "GROUP BY run_id ORDER BY MAX(id) DESC LIMIT ?",
            (workflow_id, limit),
        ).fetchall()
        return [bool(row[0]) for row in rows]

    def has_notified_failure_streak(self, workflow_id: str) -> bool:
        conn = self._connect()
        row = conn.execute(
            "SELECT 1 FROM failure_notifications WHERE workflow_id = ?", (workflow_id,)
        ).fetchone()
        return row is not None

    def mark_notified_failure_streak(self, workflow_id: str) -> None:
        conn = self._connect()
        conn.execute("INSERT OR IGNORE INTO failure_notifications (workflow_id) VALUES (?)", (workflow_id,))
        conn.commit()

    def clear_notified_failure_streak(self, workflow_id: str) -> None:
        conn = self._connect()
        conn.execute("DELETE FROM failure_notifications WHERE workflow_id = ?", (workflow_id,))
        conn.commit()

    # -- heartbeat ------------------------------------------------------------

    def set_heartbeat(self, when_iso: str) -> None:
        conn = self._connect()
        conn.execute(
            "INSERT INTO heartbeat (id, last_run_at) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET last_run_at = excluded.last_run_at",
            (when_iso,),
        )
        conn.commit()

    # -- webhooks / polling gate ---------------------------------------------

    def get_board_activity(self, instance: str, board_id: int) -> tuple[Optional[str], Optional[str]]:
        """Returns (last_ping_at, last_polled_at), either possibly None."""

        conn = self._connect()
        row = conn.execute(
            "SELECT last_ping_at, last_polled_at FROM board_activity WHERE instance = ? AND board_id = ?",
            (instance, board_id),
        ).fetchone()
        return (row[0], row[1]) if row else (None, None)

    def record_webhook_ping(self, instance: str, board_id: int, when_iso: str) -> None:
        conn = self._connect()
        conn.execute(
            "INSERT INTO board_activity (instance, board_id, last_ping_at) VALUES (?, ?, ?) "
            "ON CONFLICT(instance, board_id) DO UPDATE SET last_ping_at = excluded.last_ping_at",
            (instance, board_id, when_iso),
        )
        conn.commit()

    def record_poll(self, instance: str, board_id: int, when_iso: str) -> None:
        conn = self._connect()
        conn.execute(
            "INSERT INTO board_activity (instance, board_id, last_polled_at) VALUES (?, ?, ?) "
            "ON CONFLICT(instance, board_id) DO UPDATE SET last_polled_at = excluded.last_polled_at",
            (instance, board_id, when_iso),
        )
        conn.commit()

    def recent_webhook_pings(self, limit: int = 50) -> list[dict[str, Any]]:
        """For the website's observability page - lets an admin confirm
        Nextcloud's webhook configuration is actually reaching us."""

        conn = self._connect()
        rows = conn.execute(
            "SELECT instance, board_id, last_ping_at FROM board_activity "
            "WHERE last_ping_at IS NOT NULL ORDER BY last_ping_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [{"instance": row[0], "board_id": row[1], "last_ping_at": row[2]} for row in rows]

    # -- ActionLinkStorePort (one-time action links) -------------------------

    def create_link(
        self,
        *,
        workflow_id: str,
        event: DeckEvent,
        current_stack_id: int,
        module: str,
        params: dict[str, Any],
        variables: dict[str, Any],
        success_message: str,
        require_confirmation: bool,
        confirm_message: str = "",
        expires_at: Optional[str] = None,
        extra_steps: Optional[list[dict[str, Any]]] = None,
    ) -> str:
        token = secrets.token_urlsafe(32)
        conn = self._connect()
        conn.execute(
            "INSERT INTO action_links (token_hash, workflow_id, instance, board_id, card_id, stack_id, "
            "current_stack_id, event_type, card_json, module, params_json, variables_json, "
            "success_message, require_confirmation, status, created_at, expires_at, extra_steps_json, confirm_message) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)",
            (
                hashlib.sha256(token.encode()).hexdigest(), workflow_id, event.instance, event.board_id,
                event.card_id, event.stack_id, current_stack_id, event.event_type.value,
                json.dumps(event.card, default=str), module, json.dumps(params, default=str),
                json.dumps(variables, default=str), success_message, int(require_confirmation),
                datetime.now(timezone.utc).isoformat(), expires_at,
                json.dumps(extra_steps, default=str) if extra_steps else None, confirm_message,
            ),
        )
        conn.commit()
        return token

    def claimed_links(self) -> list[dict[str, Any]]:
        """Links the website has claimed (visited) that main.py hasn't run yet."""

        return self._links_where("status = 'claimed' ORDER BY claimed_at", ())

    def stale_running_links(self, started_before_iso: str) -> list[dict[str, Any]]:
        """Links a main.py invocation took for running but never finished -
        the process was killed (cron timeout) in between."""

        return self._links_where("status = 'running' AND running_at < ?", (started_before_iso,))

    def _links_where(self, where: str, args: tuple) -> list[dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT token_hash, workflow_id, instance, board_id, card_id, stack_id, current_stack_id, "
            "event_type, card_json, module, params_json, variables_json, extra_steps_json FROM action_links "
            f"WHERE {where}",
            args,
        ).fetchall()
        keys = ("token_hash", "workflow_id", "instance", "board_id", "card_id", "stack_id",
                "current_stack_id", "event_type", "card", "module", "params", "variables", "extra_steps")
        links = []
        for row in rows:
            link = dict(zip(keys, row))
            link["event_type"] = EventType(link["event_type"])
            for key in ("card", "params", "variables"):
                link[key] = json.loads(link[key]) if link[key] else {}
            link["extra_steps"] = json.loads(link["extra_steps"]) if link["extra_steps"] else []
            # Everything the link runs, in order: the first action, then the others.
            link["steps"] = [{"module": link["module"], "params": link["params"]}] + link["extra_steps"]
            links.append(link)
        return links

    def begin_link_run(self, token_hash: str) -> bool:
        """Atomically takes a claimed link for running - False if another
        main.py invocation got it first (two runs can overlap, e.g. cron plus
        a webhook-triggered run)."""

        conn = self._connect()
        cursor = conn.execute(
            "UPDATE action_links SET status = 'running', running_at = ? WHERE token_hash = ? AND status = 'claimed'",
            (datetime.now(timezone.utc).isoformat(), token_hash),
        )
        conn.commit()
        return cursor.rowcount == 1

    def finish_link(self, token_hash: str, error: Optional[str] = None) -> None:
        """Marks the link done/error and wipes everything it needed to run."""

        conn = self._connect()
        conn.execute(
            "UPDATE action_links SET status = ?, error = ?, finished_at = ?, card_json = NULL, "
            "params_json = NULL, variables_json = NULL, extra_steps_json = NULL WHERE token_hash = ?",
            ("error" if error else "done", error, datetime.now(timezone.utc).isoformat(), token_hash),
        )
        conn.commit()

    def purge_expired_links(self, now_iso: str) -> None:
        """Deletes links that expired without being used - nobody can open
        them any more, and they still hold the action's params."""

        conn = self._connect()
        conn.execute(
            "DELETE FROM action_links WHERE status = 'open' AND expires_at IS NOT NULL AND expires_at < ?",
            (now_iso,),
        )
        conn.commit()

    def purge_finished_links(self, older_than_iso: str) -> None:
        conn = self._connect()
        conn.execute(
            "DELETE FROM action_links WHERE status IN ('done', 'error') AND finished_at < ?",
            (older_than_iso,),
        )
        conn.commit()

    # -- DuplicateGuardPort ----------------------------------------------------

    def seen_within(self, key: str, minutes: float) -> bool:
        conn = self._connect()
        row = conn.execute("SELECT created_at FROM dedupe_keys WHERE key = ?", (key,)).fetchone()
        if row is None:
            return False
        age = datetime.now(timezone.utc) - datetime.fromisoformat(row[0])
        return age.total_seconds() < minutes * 60

    def remember(self, key: str) -> None:
        conn = self._connect()
        now = datetime.now(timezone.utc)
        conn.execute(
            "INSERT INTO dedupe_keys (key, created_at) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET created_at = excluded.created_at",
            (key, now.isoformat()),
        )
        conn.execute("DELETE FROM dedupe_keys WHERE created_at < ?", ((now - timedelta(days=8)).isoformat(),))
        conn.commit()

    # -- CopyStorePort -----------------------------------------------------------

    def record_copy(self, instance: str, board_id: int, card_id: int, workflow_id: str, depth: int) -> None:
        conn = self._connect()
        now = datetime.now(timezone.utc)
        conn.execute(
            "INSERT OR REPLACE INTO copied_cards (instance, board_id, card_id, workflow_id, depth, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (instance, board_id, card_id, workflow_id, depth, now.isoformat()),
        )
        conn.commit()

    def copy_info(self, instance: str, board_id: int, card_id: int) -> Optional[tuple[str, int]]:
        conn = self._connect()
        row = conn.execute(
            "SELECT workflow_id, depth FROM copied_cards WHERE instance = ? AND board_id = ? AND card_id = ?",
            (instance, board_id, card_id),
        ).fetchone()
        return (row[0], row[1]) if row else None

    # -- retention -----------------------------------------------------------------

    def purge_history(self, older_than_iso: str) -> None:
        """Drops execution-log rows, finished test runs and copy records older
        than the cutoff - without this the database grows with every run."""

        conn = self._connect()
        conn.execute("DELETE FROM execution_log WHERE created_at < ?", (older_than_iso,))
        conn.execute("DELETE FROM test_runs WHERE status != 'pending' AND created_at < ?", (older_than_iso,))
        conn.execute("DELETE FROM copied_cards WHERE created_at < ?", (older_than_iso,))
        conn.commit()
