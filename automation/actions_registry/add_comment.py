from __future__ import annotations

from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
from automation.core.ports.action_module import ActionContext


class AddCommentAction(WorkflowAction):
    """Adds a comment to the triggering card.

    params:
      message: str - the comment text
    """

    ACTION_NAME: ClassVar[str] = "add_comment"

    def execute(self, context: ActionContext, params: dict[str, Any]) -> None:
        context.deck.add_comment(card_id=context.event.card_id, message=params["message"])
