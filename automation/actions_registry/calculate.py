from __future__ import annotations

import operator
from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
from automation.core.ports.action_module import ActionContext

_OPS = {
    "add": operator.add,
    "subtract": operator.sub,
    "multiply": operator.mul,
    "divide": operator.truediv,
}


class CalculateAction(WorkflowAction):
    """Simple arithmetic between two numeric values - e.g. to compute a
    due-date offset in days, a count, or a derived label/priority number
    from two earlier steps' outputs.

    params:
      left: number
      right: number
      op: str - one of "add", "subtract", "multiply", "divide"

    output:
      result: number - a whole result (e.g. 4) comes back as an int, not 4.0
    """

    ACTION_NAME: ClassVar[str] = "calculate"
    LABEL: ClassVar[str] = "Berechnen"

    def default_input(self) -> dict[str, Any]:
        return {"left": 0, "right": 0, "op": "add"}

    def default_output(self) -> dict[str, Any]:
        return {"result": 0}

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        op = params.get("op") or "add"
        if op not in _OPS:
            raise ValueError(f"calculate: unknown op '{op}' (expected one of {sorted(_OPS)})")

        result = _OPS[op](float(params["left"]), float(params["right"]))
        if result == int(result):
            result = int(result)
        return {"result": result}
