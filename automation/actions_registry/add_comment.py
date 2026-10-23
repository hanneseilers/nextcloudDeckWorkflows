from __future__ import annotations

from string import Template
from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
from automation.core.ports.action_module import ActionContext


class AddCommentAction(WorkflowAction):
    """Adds a comment to the triggering card.

    $placeholder values in the message are substituted from context.variables
    (global, set via set_variable) with string.Template.safe_substitute -
    unresolved placeholders are left as-is instead of raising.

    params:
      message: str - the comment text
    """

    ACTION_NAME: ClassVar[str] = "add_comment"
    LABEL: ClassVar[str] = "Kommentar hinzufügen"
    DESCRIPTION: ClassVar[str] = "Schreibt einen Kommentar an die Karte. $name im Text wird durch eine Variable ersetzt."
    PARAM_LABELS: ClassVar[dict[str, str]] = {"message": "Kommentar"}
    PARAM_HELP: ClassVar[dict[str, str]] = {"message": "Variablen aus \"Variable setzen\" mit $name einsetzen, z. B. Ticket $nummer."}

    def default_input(self) -> dict[str, Any]:
        return {"message": ""}

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        message = Template(params["message"]).safe_substitute(**context.variables)
        context.deck.add_comment(card_id=context.event.card_id, message=message)
        return {}
