from __future__ import annotations

from typing import Any, Optional

from automation.adapters.nextcloud.client import NextcloudClient

DECK_API = "/index.php/apps/deck/api/v1.1"
COMMENTS_API = "/ocs/v2.php/apps/comments/api/v1/deckCard"


class NextcloudDeckGateway:
    """Implements DeckGatewayPort against the Nextcloud Deck REST API."""

    def __init__(self, client: NextcloudClient) -> None:
        self._client = client

    def list_boards(self) -> list[dict[str, Any]]:
        return self._client.get(f"{DECK_API}/boards") or []

    def list_stacks(self, board_id: int) -> list[dict[str, Any]]:
        return self._client.get(f"{DECK_API}/boards/{board_id}/stacks") or []

    def list_cards(self, board_id: int, stack_id: int) -> list[dict[str, Any]]:
        for stack in self.list_stacks(board_id):
            if stack.get("id") == stack_id:
                return stack.get("cards", [])
        return []

    def list_labels(self, board_id: int) -> list[dict[str, Any]]:
        # The single-board endpoint embeds the board's labels (not verified
        # against a live instance - same assumption as the website's picker).
        board = self._client.get(f"{DECK_API}/boards/{board_id}") or {}
        return board.get("labels") or []

    def set_title(self, board_id: int, stack_id: int, card_id: int, title: str) -> None:
        self._update_card(board_id, stack_id, card_id, title=title)

    def set_description(self, board_id: int, stack_id: int, card_id: int, description: str) -> None:
        self._update_card(board_id, stack_id, card_id, description=description)

    def set_due_date(self, board_id: int, stack_id: int, card_id: int, due_date: Optional[str]) -> None:
        self._update_card(board_id, stack_id, card_id, duedate=due_date)

    def move_card(
        self, board_id: int, stack_id: int, card_id: int, target_stack_id: int, order: int = 0
    ) -> None:
        self._client.put(
            f"{DECK_API}/boards/{board_id}/stacks/{stack_id}/cards/{card_id}/reorder",
            json={"stackId": target_stack_id, "order": order},
        )

    def add_label(self, board_id: int, stack_id: int, card_id: int, label_id: int) -> None:
        # Deck's documented endpoint is PUT .../assignLabel with the label id in
        # the body - a PUT to .../label/{id} is answered with 405 by real instances.
        self._client.put(
            f"{DECK_API}/boards/{board_id}/stacks/{stack_id}/cards/{card_id}/assignLabel",
            json={"labelId": label_id},
        )

    def assign_user(self, board_id: int, stack_id: int, card_id: int, user_id: str) -> None:
        self._client.put(
            f"{DECK_API}/boards/{board_id}/stacks/{stack_id}/cards/{card_id}/assignUser",
            json={"userId": user_id},
        )

    def unassign_user(self, board_id: int, stack_id: int, card_id: int, user_id: str) -> None:
        self._client.put(
            f"{DECK_API}/boards/{board_id}/stacks/{stack_id}/cards/{card_id}/unassignUser",
            json={"userId": user_id},
        )

    def add_comment(self, card_id: int, message: str) -> None:
        self._client.post(f"{COMMENTS_API}/{card_id}", json={"message": message})

    def create_card(self, board_id: int, stack_id: int, title: str, description: str = "") -> dict[str, Any]:
        """Creates a fresh card - nothing but a title (and optionally a
        description) is set, so a copy made this way carries no labels,
        assignees or due date. The description is written with a follow-up
        update instead of in the create call, since only title/type/order
        are guaranteed create parameters across Deck versions."""

        created = self._client.post(
            f"{DECK_API}/boards/{board_id}/stacks/{stack_id}/cards",
            json={"title": title, "type": "plain", "order": 0},
        ) or {}
        if description and created.get("id") is not None:
            self.set_description(board_id, stack_id, created["id"], description)
            created["description"] = description
        return created

    def _update_card(self, board_id: int, stack_id: int, card_id: int, **fields: Any) -> None:
        # The Deck API's card update endpoint replaces the resource, so the current
        # card is fetched first and only the requested field(s) are changed on top -
        # this avoids accidentally clearing title/description/duedate on every call.
        path = f"{DECK_API}/boards/{board_id}/stacks/{stack_id}/cards/{card_id}"
        card = self._client.get(path) or {}
        owner = card.get("owner")
        if isinstance(owner, dict):
            owner = owner.get("uid") or owner.get("primaryKey")
        # Deck's update also expects type/owner/order (its controller declares
        # them as parameters) - sent back unchanged so they're never reset.
        payload = {
            "title": card.get("title"),
            "type": card.get("type") or "plain",
            "owner": owner,
            "order": card.get("order") or 0,
            "description": card.get("description"),
            "duedate": card.get("duedate"),
        }
        payload.update(fields)
        self._client.put(path, json=payload)
