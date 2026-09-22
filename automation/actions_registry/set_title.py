from __future__ import annotations

from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
from automation.core.ports.action_module import ActionContext


class SetTitleAction(WorkflowAction):
    """Renames the triggering card (changes its title).

    params:
      title: str - the new card title
    """

    ACTION_NAME: ClassVar[str] = "set_title"

    def execute(self, context: ActionContext, params: dict[str, Any]) -> None:
        context.deck.set_title(
            board_id=context.event.board_id,
            stack_id=context.current_stack_id,
            card_id=context.event.card_id,
            title=params["title"],
        )
