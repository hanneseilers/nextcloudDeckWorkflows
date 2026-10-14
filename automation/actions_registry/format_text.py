from __future__ import annotations

from string import Template
from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
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
      values: dict - placeholder name -> value, e.g. {"title": {"$ref": "card.title"}}

    output:
      text: str - the substituted text (an unresolved placeholder is left
        as-is rather than raising, same as add_comment/send_email)
    """

    ACTION_NAME: ClassVar[str] = "format_text"

    def default_input(self) -> dict[str, Any]:
        return {"template": "", "values": {}}

    def default_output(self) -> dict[str, Any]:
        return {"text": ""}

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        template = params.get("template") or ""
        values = params.get("values") or {}
        return {"text": Template(template).safe_substitute(**values)}
