from __future__ import annotations

from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
from automation.core.ports.action_module import ActionContext


class AddLabelAction(WorkflowAction):
    """Adds an existing Deck label (by its numeric id) to the triggering card.

    params:
      label_id: int - id of an existing label on the card's board
    """

    ACTION_NAME: ClassVar[str] = "add_label"

    def execute(self, context: ActionContext, params: dict[str, Any]) -> None:
        context.deck.add_label(
            board_id=context.event.board_id,
            stack_id=context.current_stack_id,
            card_id=context.event.card_id,
            label_id=params["label_id"],
        )
