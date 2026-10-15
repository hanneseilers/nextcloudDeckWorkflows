from __future__ import annotations

import logging
from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
from automation.core.ports.action_module import ActionContext

logger = logging.getLogger(__name__)


class LogAction(WorkflowAction):
    """Writes the triggering event to the log. Reference implementation / smoke-test
    action - copy this file as a starting point for a new capability."""

    ACTION_NAME: ClassVar[str] = "log_action"
    LABEL: ClassVar[str] = "Eintrag protokollieren"

    def default_input(self) -> dict[str, Any]:
        return {"message": ""}

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        logger.info(
            "Workflow triggered: event=%s card=%s stack=%s message=%s",
            context.event.event_type.value,
            context.event.card_id,
            context.event.stack_id,
            params.get("message", ""),
        )
        return {}
