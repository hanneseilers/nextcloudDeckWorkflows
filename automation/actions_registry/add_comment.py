from __future__ import annotations

from string import Template
from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
from automation.adapters.text_templates import load_template_text
from automation.core.ports.action_module import ActionContext


class AddCommentAction(WorkflowAction):
    """Adds a comment to the triggering card.

    $placeholder values in the message are substituted from context.variables
    (global, set via set_variable) with string.Template.safe_substitute -
    unresolved placeholders are left as-is instead of raising.

    params:
      message: str - the comment text
      text_template: str (optional) - name of a text template
        (config/text_templates/<name>.txt, edited on the website's "Vorlagen"
        page); its text is used instead of `message` (a `Subject:` line of the
        template, meant for e-mails, is dropped)
    """

    ACTION_NAME: ClassVar[str] = "add_comment"
    LABEL: ClassVar[str] = "Kommentar hinzufügen"
    DESCRIPTION: ClassVar[str] = "Schreibt einen Kommentar an die Karte. $name im Text wird durch eine Variable ersetzt."
    PARAM_LABELS: ClassVar[dict[str, str]] = {"message": "Kommentar (Text mit Platzhaltern)", "text_template": "Textvorlage (optional)"}
    PARAM_HELP: ClassVar[dict[str, str]] = {"message": "Variablen aus \"Variable setzen\" mit $name einsetzen, z. B. Ticket $nummer.", "text_template": "Eine Textvorlage (Menü „Vorlagen“) - ihr Text ersetzt das Feld Kommentar; $name darin wird wie dort durch Variablen ersetzt."}

    OUTPUT_LABELS: ClassVar[dict[str, str]] = {"message": "Kommentar"}

    def default_input(self) -> dict[str, Any]:
        return {"message": "", "text_template": None}

    def default_output(self) -> dict[str, Any]:
        return {"message": ""}

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        text = load_template_text(params["text_template"]) if params.get("text_template") else params["message"]
        message = Template(text).safe_substitute(**context.variables)
        context.deck.add_comment(card_id=context.event.card_id, message=message)
        return {"message": message}  # as posted, i.e. with $placeholders filled in
