from __future__ import annotations

from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
from automation.core.ports.action_module import ActionContext


class SetDueDateAction(WorkflowAction):
    """Sets (or clears) the due date of the triggering card.

    params:
      due_date: str | None - ISO-8601 timestamp (e.g. "2026-01-31T00:00:00+00:00"),
                              or null/omitted to clear the due date
    """

    ACTION_NAME: ClassVar[str] = "set_due_date"

    def execute(self, context: ActionContext, params: dict[str, Any]) -> None:
        context.deck.set_due_date(
            board_id=context.event.board_id,
            stack_id=context.current_stack_id,
            card_id=context.event.card_id,
            due_date=params.get("due_date"),
        )
