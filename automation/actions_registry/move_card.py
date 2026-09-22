from __future__ import annotations

from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
from automation.core.ports.action_module import ActionContext


class MoveCardAction(WorkflowAction):
    """Moves the triggering card to a different stack (column).

    params:
      target_stack_id: int - id of the destination stack
      order: int (optional, default 0) - position within the destination stack
    """

    ACTION_NAME: ClassVar[str] = "move_card"

    def default_input(self) -> dict[str, Any]:
        return {"target_stack_id": 0, "order": 0}

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        target_stack_id = params["target_stack_id"]
        context.deck.move_card(
            board_id=context.event.board_id,
            stack_id=context.current_stack_id,
            card_id=context.event.card_id,
            target_stack_id=target_stack_id,
            order=params.get("order", 0),
        )
        # Keep later actions in the same chain pointed at the card's new stack.
        context.current_stack_id = target_stack_id
        return {}
