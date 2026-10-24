from __future__ import annotations

import logging
from typing import Any, Optional

from automation.adapters.nextcloud.client import NextcloudClient

logger = logging.getLogger(__name__)

DECK_API = "/index.php/apps/deck/api/v1.1"
# Deck's own OCS comments API (documented at deck.readthedocs.io, "OCS API").
DECK_OCS_API = "/ocs/v2.php/apps/deck/api/v1.0"
# Deck rejects comments / card titles longer than this (titles with a 400).
COMMENT_MAX_LENGTH = 1000
TITLE_MAX_LENGTH = 255


def _shorten(text: str, limit: int, what: str) -> str:
    if len(text) <= limit:
        return text
    logger.warning("%s is %d characters long, Deck allows %d - shortened", what, len(text), limit)
    return text[: limit - 1] + "…"


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

    def get_card(self, board_id: int, stack_id: int, card_id: int) -> dict[str, Any]:
        return self._client.get(f"{DECK_API}/boards/{board_id}/stacks/{stack_id}/cards/{card_id}") or {}

    def set_title(self, board_id: int, stack_id: int, card_id: int, title: str) -> None:
        self._update_card(
            board_id, stack_id, card_id, title=_shorten(title, TITLE_MAX_LENGTH, f"Title of card {card_id}")
        )

    def set_description(self, board_id: int, stack_id: int, card_id: int, description: str) -> None:
        self._update_card(board_id, stack_id, card_id, description=description)

    def set_due_date(self, board_id: int, stack_id: int, card_id: int, due_date: Optional[str]) -> None:
        self._update_card(board_id, stack_id, card_id, duedate=due_date)

    def move_card(
        self, board_id: int, stack_id: int, card_id: int, target_stack_id: int, order: int = 0
    ) -> None:
        # The TARGET stack goes into the URL: Deck's route has a {stackId} and the
        # controller reads exactly that one (a route parameter wins over a body
        # field of the same name), so a request addressed to the card's current
        # stack "moves" it to where it already is - no error, nothing happens.
        # (stack_id, the card's current stack, is therefore not used here.)
        self._client.put(
            f"{DECK_API}/boards/{board_id}/stacks/{target_stack_id}/cards/{card_id}/reorder",
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
        message = _shorten(message, COMMENT_MAX_LENGTH, f"Comment on card {card_id}")
        self._client.post(f"{DECK_OCS_API}/cards/{card_id}/comments", json={"message": message})

    def create_card(self, board_id: int, stack_id: int, title: str, description: str = "") -> dict[str, Any]:
        """Creates a fresh card - nothing but a title (and optionally a
        description) is set, so a copy made this way carries no labels,
        assignees or due date. The description is written with a follow-up
        update instead of in the create call, since only title/type/order
        are guaranteed create parameters across Deck versions."""

        title = _shorten(title, TITLE_MAX_LENGTH, "Title of the new card")
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
        # Deck's update takes the card's stack from the URL and *sets* it: with a
        # stale stack id (the card was moved since the event, by someone else or
        # another workflow) it would silently move the card back. The card's
        # actual stack comes from its own data (GET ignores the stack in the URL).
        if card.get("stackId") is not None:
            path = f"{DECK_API}/boards/{board_id}/stacks/{card['stackId']}/cards/{card_id}"
        owner = card.get("owner")
        if isinstance(owner, dict):
            owner = owner.get("uid") or owner.get("primaryKey")
        # Deck's update (CardApiController::update) requires title, type and owner
        # (description, order, duedate are optional) - the card's current values
        # are sent back so nothing is reset.
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
