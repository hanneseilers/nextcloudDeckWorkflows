from __future__ import annotations

from typing import Any, Iterable, Protocol

from automation.core.domain.models import DeckEvent


class EventSourcePort(Protocol):
    """Produces the DeckEvents that happened on a board since the last call."""

    def poll(self, instance: str, board_id: int) -> Iterable[DeckEvent]: ...


class SnapshotStorePort(Protocol):
    """Persists the last known per-card state of a board so events can be diffed against it.

    Snapshot shape: {card_id: {"stack_id": int, "last_modified": int}}
    """

    def load(self, instance: str, board_id: int) -> dict[int, dict[str, Any]]: ...

    def save(self, instance: str, board_id: int, snapshot: dict[int, dict[str, Any]]) -> None: ...
