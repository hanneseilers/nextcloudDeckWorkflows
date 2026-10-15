from __future__ import annotations

from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
from automation.core.ports.action_module import ActionContext


def _extract(data: Any, path: str) -> Any:
    if not path:
        return data

    value = data
    for part in path.split("."):
        if isinstance(value, dict):
            if part not in value:
                raise KeyError(f"extract_field: key {part!r} not found")
            value = value[part]
        elif isinstance(value, list):
            try:
                index = int(part)
            except ValueError:
                raise ValueError(f"extract_field: {part!r} is not a valid list index") from None
            try:
                value = value[index]
            except IndexError:
                raise IndexError(f"extract_field: index {index} out of range") from None
        else:
            raise TypeError(f"extract_field: cannot look up {part!r} in a {type(value).__name__}")
    return value


class ExtractFieldAction(WorkflowAction):
    """Pulls one value out of a nested dict/list structure by path - the
    general-purpose counterpart to {"$ref": "<step>.<field>"} (which only
    traverses dicts): this module also walks into lists by numeric index,
    e.g. a path of "events.0.title".

    Raises a clear error if the path doesn't resolve (missing key, index out
    of range, indexing into something that's neither dict nor list) - caught
    and recorded like any other action's error by the engine's existing
    per-step failure isolation.

    params:
      data: Any - typically {"$ref": "<step>.<field>"} pointing at another
        step's whole output, but any literal value works too
      path: str - dot-separated keys/indices, e.g. "title" or "0.start";
        empty/omitted returns `data` unchanged

    output:
      value: Any - whatever was found at that path
    """

    ACTION_NAME: ClassVar[str] = "extract_field"
    LABEL: ClassVar[str] = "Feld extrahieren"

    def default_input(self) -> dict[str, Any]:
        return {"data": {}, "path": ""}

    def default_output(self) -> dict[str, Any]:
        return {"value": None}

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        return {"value": _extract(params.get("data"), params.get("path", ""))}
