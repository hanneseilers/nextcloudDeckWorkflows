from __future__ import annotations

from typing import Any, Iterator

from automation.core.domain.models import DeckEvent, EventType
from automation.core.ports.deck_gateway import DeckGatewayPort
from automation.core.ports.event_source import SnapshotStorePort


def _assignee_ids(card: dict[str, Any]) -> set[str]:
    """Best-effort extraction of assigned user ids from a Deck card's
    `assignedUsers`. Not verified against a live Nextcloud instance - tries
    the participant-wrapped shape first, then a couple of flatter fallbacks,
    and simply yields no ids (never raises) if the shape doesn't match any of
    them, so a schema mismatch degrades to "no CARD_ASSIGNED event" rather
    than crashing the poll.
    """

    ids: set[str] = set()
    for entry in card.get("assignedUsers") or []:
        if not isinstance(entry, dict):
            continue
        participant = entry.get("participant")
        if isinstance(participant, dict) and participant.get("uid"):
            ids.add(str(participant["uid"]))
        elif entry.get("uid"):
            ids.add(str(entry["uid"]))
        elif entry.get("id") is not None:
            ids.add(str(entry["id"]))
    return ids


class PollingEventSource:
    """Implements EventSourcePort by diffing the current board state against the
    snapshot from the previous run. Needed because a shared-webspace cron job has no
    way to receive a live push/webhook from Nextcloud.

    `poll()` does NOT persist the new snapshot by itself - call `commit()`
    once the caller has fully handled every event `poll()` returned. If the
    process dies in between (e.g. SIGKILL), the snapshot stays at its old
    value, so the next run detects the exact same events again and reruns
    their workflows - "at least once" rather than silently losing events.
    A board whose events were never committed is held in `_pending` until
    `commit()` (or a fresh `poll()` for that board) replaces it.
    """

    def __init__(self, deck: DeckGatewayPort, snapshots: SnapshotStorePort) -> None:
        self._deck = deck
        self._snapshots = snapshots
        self._pending: dict[tuple[str, int], dict[int, dict[str, Any]]] = {}

    def poll(self, instance: str, board_id: int) -> list[DeckEvent]:
        current = self._fetch_current(board_id)
        previous = self._snapshots.load(instance, board_id)
        events = list(self._diff(instance, board_id, previous, current))
        self._pending[(instance, board_id)] = current
        return events

    def commit(self, instance: str, board_id: int) -> None:
        current = self._pending.pop((instance, board_id), None)
        if current is None:
            return
        self._snapshots.save(instance, board_id, {
            card_id: {
                "stack_id": state["stack_id"],
                "last_modified": state["last_modified"],
                "duedate": state["duedate"],
                "description": state["description"],
                "assignee_ids": sorted(state["assignee_ids"]),
            }
            for card_id, state in current.items()
        })

    def _fetch_current(self, board_id: int) -> dict[int, dict[str, Any]]:
        snapshot: dict[int, dict[str, Any]] = {}
        for stack in self._deck.list_stacks(board_id):
            for card in stack.get("cards", []):
                snapshot[card["id"]] = {
                    "stack_id": stack["id"],
                    "last_modified": card.get("lastModified", 0),
                    "duedate": card.get("duedate"),
                    "description": card.get("description"),
                    "assignee_ids": _assignee_ids(card),
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
                continue

            if prev_state["stack_id"] != state["stack_id"]:
                yield DeckEvent(
                    instance=instance,
                    board_id=board_id,
                    event_type=EventType.CARD_MOVED,
                    card_id=card_id,
                    stack_id=state["stack_id"],
                    previous_stack_id=prev_state["stack_id"],
                    card=state["card"],
                )

            prev_assignees = set(prev_state.get("assignee_ids") or [])
            if state["assignee_ids"] - prev_assignees:
                # Fires for a newly added assignee specifically (not a removal) -
                # matches "wenn eine neue Person assigned wurde".
                yield DeckEvent(
                    instance=instance,
                    board_id=board_id,
                    event_type=EventType.CARD_ASSIGNED,
                    card_id=card_id,
                    stack_id=state["stack_id"],
                    card=state["card"],
                )

            if prev_state.get("duedate") != state["duedate"]:
                yield DeckEvent(
                    instance=instance,
                    board_id=board_id,
                    event_type=EventType.CARD_DUE_DATE_CHANGED,
                    card_id=card_id,
                    stack_id=state["stack_id"],
                    card=state["card"],
                )

            if prev_state.get("description") != state["description"]:
                yield DeckEvent(
                    instance=instance,
                    board_id=board_id,
                    event_type=EventType.CARD_DESCRIPTION_CHANGED,
                    card_id=card_id,
                    stack_id=state["stack_id"],
                    card=state["card"],
                )

            if prev_state["last_modified"] != state["last_modified"]:
                # Fires on *any* change, in addition to the more specific
                # events above - an existing workflow watching card_updated
                # keeps working exactly as before.
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
