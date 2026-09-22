from __future__ import annotations

from typing import Any, Iterator

from automation.core.domain.models import DeckEvent, EventType
from automation.core.ports.deck_gateway import DeckGatewayPort
from automation.core.ports.event_source import SnapshotStorePort


class PollingEventSource:
    """Implements EventSourcePort by diffing the current board state against the
    snapshot from the previous run. Needed because a shared-webspace cron job has no
    way to receive a live push/webhook from Nextcloud.
    """

    def __init__(self, deck: DeckGatewayPort, snapshots: SnapshotStorePort) -> None:
        self._deck = deck
        self._snapshots = snapshots

    def poll(self, instance: str, board_id: int) -> list[DeckEvent]:
        current = self._fetch_current(board_id)
        previous = self._snapshots.load(instance, board_id)
        events = list(self._diff(instance, board_id, previous, current))
        self._snapshots.save(instance, board_id, {
            card_id: {"stack_id": state["stack_id"], "last_modified": state["last_modified"]}
            for card_id, state in current.items()
        })
        return events

    def _fetch_current(self, board_id: int) -> dict[int, dict[str, Any]]:
        snapshot: dict[int, dict[str, Any]] = {}
        for stack in self._deck.list_stacks(board_id):
            for card in stack.get("cards", []):
                snapshot[card["id"]] = {
                    "stack_id": stack["id"],
                    "last_modified": card.get("lastModified", 0),
                    "card": card,
                }
        return snapshot

    def _diff(
        self,
        instance: str,
        board_id: int,
        previous: dict[int, dict[str, Any]],
        current: dict[int, dict[str, Any]],
    ) -> Iterator[DeckEvent]:
        for card_id, state in current.items():
            prev_state = previous.get(card_id)
            if prev_state is None:
                yield DeckEvent(
                    instance=instance,
                    board_id=board_id,
                    event_type=EventType.CARD_CREATED,
                    card_id=card_id,
                    stack_id=state["stack_id"],
                    card=state["card"],
                )
            elif prev_state["stack_id"] != state["stack_id"]:
                yield DeckEvent(
                    instance=instance,
                    board_id=board_id,
                    event_type=EventType.CARD_MOVED,
                    card_id=card_id,
                    stack_id=state["stack_id"],
                    previous_stack_id=prev_state["stack_id"],
                    card=state["card"],
                )
            elif prev_state["last_modified"] != state["last_modified"]:
                yield DeckEvent(
                    instance=instance,
                    board_id=board_id,
                    event_type=EventType.CARD_UPDATED,
                    card_id=card_id,
                    stack_id=state["stack_id"],
                    card=state["card"],
                )

        for card_id, prev_state in previous.items():
            if card_id not in current:
                yield DeckEvent(
                    instance=instance,
                    board_id=board_id,
                    event_type=EventType.CARD_DELETED,
                    card_id=card_id,
                    stack_id=prev_state["stack_id"],
                )
