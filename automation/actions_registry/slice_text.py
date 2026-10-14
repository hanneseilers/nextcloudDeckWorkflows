from __future__ import annotations

from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
from automation.core.ports.action_module import ActionContext


class SliceTextAction(WorkflowAction):
    """Extracts the part of `text` between two delimiter strings.

    - `start` (optional): the slice begins right after the first occurrence of
      this substring. Omitted/empty means "from the beginning of text".
    - `end` (optional): the slice ends right before the first occurrence of
      this substring *after* the start position. Omitted/empty means "to the
      end of text".

    Raises a clear error if a given delimiter isn't found in `text` - caught
    and recorded by the engine's existing per-step failure isolation
    (WorkflowEngine._run_action_step), same as any other action's errors, so a
    bad delimiter fails only this one step rather than the whole workflow.

    params:
      text: str
      start: str | None - delimiter to slice after
      end: str | None - delimiter to slice before

    output:
      text: str - the extracted substring
    """

    ACTION_NAME: ClassVar[str] = "slice_text"

    def default_input(self) -> dict[str, Any]:
        return {"text": "", "start": None, "end": None}

    def default_output(self) -> dict[str, Any]:
        return {"text": ""}

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        text = params["text"]
        start = params.get("start")
        end = params.get("end")

        start_index = 0
        if start:
            found = text.find(start)
            if found == -1:
                raise ValueError(f"slice_text: start delimiter {start!r} not found in text")
            start_index = found + len(start)

        end_index = len(text)
        if end:
            found = text.find(end, start_index)
            if found == -1:
                raise ValueError(f"slice_text: end delimiter {end!r} not found in text (after 'start')")
            end_index = found

        return {"text": text[start_index:end_index]}
