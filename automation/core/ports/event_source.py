from __future__ import annotations

from typing import Any, Iterable, Optional, Protocol

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

    def save_card(
        self, instance: str, board_id: int, card_id: int, state: Optional[dict[str, Any]]
    ) -> None:
        """Updates (or, with state=None, removes) just one card's stored state -
        lets the event source record progress card by card while a poll's
        events are being handled."""
        ...
