from __future__ import annotations

from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
from automation.core.ports.action_module import ActionContext


class SetVariableAction(WorkflowAction):
    """Stores a value under a workflow-chosen name as a global variable for the
    rest of this run.

    Later steps can read it back two ways:
      - structured: {"$ref": "vars.<name>"} in any param, same as any step's output
      - free text: directly as a $<name> placeholder in actions that substitute
        placeholders (send_email, add_comment) - no extra wiring needed there

    params:
      name: str - the variable's name (also the placeholder name in text)
      value: Any - literal or {"$ref": ...}; already resolved by the engine
        before this runs
    """

    ACTION_NAME: ClassVar[str] = "set_variable"
    LABEL: ClassVar[str] = "Variable setzen"

    def default_input(self) -> dict[str, Any]:
        return {"name": "", "value": None}

    def default_output(self) -> dict[str, Any]:
        return {"name": "", "value": None}

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        name = params["name"]
        value = params.get("value")
        context.variables[name] = value
        return {"name": name, "value": value}
