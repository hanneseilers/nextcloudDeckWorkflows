from __future__ import annotations

from typing import Any

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

    def add_label(self, board_id: int, card_id: int, label_id: int) -> None:
        self._client.put(f"{DECK_API}/boards/{board_id}/cards/{card_id}/label/{label_id}")

    def move_card(self, board_id: int, card_id: int, target_stack_id: int, order: int = 0) -> None:
        self._client.put(
            f"{DECK_API}/boards/{board_id}/cards/{card_id}/reorder",
            json={"stackId": target_stack_id, "order": order},
        )

    def add_comment(self, card_id: int, message: str) -> None:
        self._client.post(f"{COMMENTS_API}/{card_id}", json={"message": message})
