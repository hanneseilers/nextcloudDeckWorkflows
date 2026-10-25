from __future__ import annotations

from string import Template
from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
from automation.adapters.text_templates import load_template_text
from automation.core.domain.date_values import with_date_values
from automation.core.ports.action_module import ActionContext


class FormatTextAction(WorkflowAction):
    """Combines several values into one text string via $placeholder
    substitution. Unlike add_comment/send_email (which only substitute
    global variables, see set_variable), the values here are explicit
    per-call via `values` - typically each one a {"$ref": ...} - so any
    step's output (not just a global variable) can be woven into one
    literal string, usable as input to any module that doesn't do its own
    substitution (set_title, set_description, forget_random_number, ...).

    params:
      template: str - text with $name placeholders
      text_template: str (optional) - name of a text template
        (config/text_templates/<name>.txt, edited on the website's "Vorlagen"
        page); its text is used instead of `template`
      values: dict - placeholder name -> value, e.g. {"title": {"$ref": "card.title"}}

    output:
      text: str - the substituted text (an unresolved placeholder is left
        as-is rather than raising, same as add_comment/send_email)
    """

    ACTION_NAME: ClassVar[str] = "format_text"
    LABEL: ClassVar[str] = "Text zusammensetzen"
    DESCRIPTION: ClassVar[str] = "Setzt einen Text aus festen Teilen und Werten zusammen."
    PARAM_LABELS: ClassVar[dict[str, str]] = {"template": "Text (mit Platzhaltern)", "text_template": "Textvorlage (optional)", "values": "Werte"}
    PARAM_HELP: ClassVar[dict[str, str]] = {"text_template": "Eine Textvorlage (Menü „Vorlagen“) - ihr Text ersetzt das Feld Text.", "template": "Beispiel: Ticket $nummer: $titel - jedes $name wird durch den gleichnamigen Eintrag unter Werte ersetzt. Immer da, ohne Eintrag: $date (Datum und Uhrzeit), $day (Datum), $weekday (Wochentag).", "values": "Beispiel: {\"nummer\": {\"$ref\": \"schritt1.number\"}, \"titel\": {\"$ref\": \"card.title\"}} - links der Name, rechts der Wert."}
    OUTPUT_LABELS: ClassVar[dict[str, str]] = {"text": "Text"}

    def default_input(self) -> dict[str, Any]:
        return {"template": "", "text_template": None, "values": {}}

    def default_output(self) -> dict[str, Any]:
        return {"text": ""}

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        template = load_template_text(params["text_template"]) if params.get("text_template") else params.get("template") or ""
        values = params.get("values") or {}
        return {"text": Template(template).safe_substitute(**with_date_values(values, context.display_timezone))}
