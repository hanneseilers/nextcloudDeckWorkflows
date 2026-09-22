from __future__ import annotations

from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
from automation.core.ports.action_module import ActionContext


class SetDescriptionAction(WorkflowAction):
    """Replaces the content/description of the triggering card.

    params:
      description: str - the new card description (Markdown, as used by Deck)
    """

    ACTION_NAME: ClassVar[str] = "set_description"

    def execute(self, context: ActionContext, params: dict[str, Any]) -> None:
        context.deck.set_description(
            board_id=context.event.board_id,
            stack_id=context.current_stack_id,
            card_id=context.event.card_id,
            description=params["description"],
        )
