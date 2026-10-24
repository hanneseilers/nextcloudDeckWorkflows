from __future__ import annotations

from typing import Any, Optional


class NullDeckGateway:
    """Stands in for DeckGatewayPort when running a schedule-triggered
    workflow (main.py::_process_schedules) - there is no real triggering
    card/board for it to act on. Raises a clear error if an action actually
    tries to use it, instead of a confusing 404 against card id 0 or
    silently doing nothing - a schedule-triggered workflow should stick to
    card-independent actions (send_email, log_action, calculate,
    generate_random_number, ...).
    """

    def _unsupported(self) -> Any:
        raise RuntimeError(
            "This action needs a real Nextcloud card/board, but this workflow is "
            "schedule-triggered (no triggering card) - use a card-independent "
            "action instead (send_email, log_action, calculate, "
            "generate_random_number, ...)."
        )

    def list_boards(self) -> list[dict[str, Any]]:
        return self._unsupported()

    def list_stacks(self, board_id: int) -> list[dict[str, Any]]:
        return self._unsupported()

    def list_cards(self, board_id: int, stack_id: int) -> list[dict[str, Any]]:
        return self._unsupported()

    def list_labels(self, board_id: int) -> list[dict[str, Any]]:
        return self._unsupported()

    def set_title(self, board_id: int, stack_id: int, card_id: int, title: str) -> None:
        self._unsupported()

    def set_description(self, board_id: int, stack_id: int, card_id: int, description: str) -> None:
        self._unsupported()

    def set_due_date(self, board_id: int, stack_id: int, card_id: int, due_date: Optional[str]) -> None:
        self._unsupported()

    def move_card(
        self, board_id: int, stack_id: int, card_id: int, target_stack_id: int, order: int = 0
    ) -> None:
        self._unsupported()

    def add_label(self, board_id: int, stack_id: int, card_id: int, label_id: int) -> None:
        self._unsupported()

    def assign_user(self, board_id: int, stack_id: int, card_id: int, user_id: str) -> None:
        self._unsupported()

    def unassign_user(self, board_id: int, stack_id: int, card_id: int, user_id: str) -> None:
        self._unsupported()

    def add_comment(self, card_id: int, message: str) -> None:
        self._unsupported()

    def create_card(self, board_id: int, stack_id: int, title: str, description: str = "") -> dict[str, Any]:
        return self._unsupported()
