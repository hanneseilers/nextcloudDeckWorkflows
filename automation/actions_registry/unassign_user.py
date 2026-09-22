from __future__ import annotations

from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
from automation.core.ports.action_module import ActionContext


class UnassignUserAction(WorkflowAction):
    """Removes a user's assignment from the triggering card.

    params:
      user_id: str - Nextcloud user id to unassign
    """

    ACTION_NAME: ClassVar[str] = "unassign_user"

    def default_input(self) -> dict[str, Any]:
        return {"user_id": ""}

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        context.deck.unassign_user(
            board_id=context.event.board_id,
            stack_id=context.current_stack_id,
            card_id=context.event.card_id,
            user_id=params["user_id"],
        )
        return {}
