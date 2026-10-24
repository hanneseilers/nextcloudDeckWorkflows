from __future__ import annotations

from typing import Any, Optional, Protocol


class DeckGatewayPort(Protocol):
    """Read/write access to Nextcloud Deck data for a single Nextcloud instance.

    Every card mutation takes the card's current `stack_id`, because the Deck API
    scopes card updates under their current stack - actions get it for free from
    the triggering DeckEvent, so callers never have to look it up themselves.
    """

    def list_boards(self) -> list[dict[str, Any]]: ...

    def list_stacks(self, board_id: int) -> list[dict[str, Any]]: ...

    def list_cards(self, board_id: int, stack_id: int) -> list[dict[str, Any]]: ...

    def list_labels(self, board_id: int) -> list[dict[str, Any]]:
        """The board's labels: [{"id": ..., "title": ...}, ...]."""
        ...

    def get_card(self, board_id: int, stack_id: int, card_id: int) -> dict[str, Any]:
        """The card as Deck returns it right now (labels, assignedUsers, ...)."""
        ...

    def set_title(self, board_id: int, stack_id: int, card_id: int, title: str) -> None: ...

    def set_description(self, board_id: int, stack_id: int, card_id: int, description: str) -> None: ...

    def set_due_date(
        self, board_id: int, stack_id: int, card_id: int, due_date: Optional[str]
    ) -> None: ...

    def move_card(
        self, board_id: int, stack_id: int, card_id: int, target_stack_id: int, order: int = 0
    ) -> None: ...

    def add_label(self, board_id: int, stack_id: int, card_id: int, label_id: int) -> None: ...

    def assign_user(self, board_id: int, stack_id: int, card_id: int, user_id: str) -> None: ...

    def unassign_user(self, board_id: int, stack_id: int, card_id: int, user_id: str) -> None: ...

    def add_comment(self, card_id: int, message: str) -> None: ...

    def create_card(
        self, board_id: int, stack_id: int, title: str, description: str = ""
    ) -> dict[str, Any]: ...
