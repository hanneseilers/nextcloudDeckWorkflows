from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
"""

# Added after the fact (see _SCHEMA above) via ALTER TABLE so an existing
# state.sqlite3 from before this field existed keeps working - CREATE TABLE
# IF NOT EXISTS alone wouldn't add it to an already-existing table.
_EXTRA_COLUMN = "extra"


class SqliteStateStore:
    """Implements SnapshotStorePort (board diffing state) and ExecutionLogPort
    (workflow run history). SQLite instead of YAML because this is machine-written,
    frequently updated runtime data with no need for manual editing - unlike the
    workflow definitions themselves.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = str(db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.executescript(_SCHEMA)
            try:
                conn.execute(f"ALTER TABLE board_snapshots ADD COLUMN {_EXTRA_COLUMN} TEXT")
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

    def record(self, result: ExecutionResult) -> None:
        with closing(self._connect()) as conn:
            for action_result in result.action_results:
                conn.execute(
                    "INSERT INTO execution_log "
                    "(workflow_id, event_type, card_id, success, error, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        result.workflow_id,
                        result.event.event_type.value,
                        result.event.card_id,
                        int(action_result.success),
                        action_result.error,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
            conn.commit()
