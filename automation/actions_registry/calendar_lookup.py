from __future__ import annotations

from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
from automation.core.ports.action_module import ActionContext


class CalendarLookupAction(WorkflowAction):
    """Reference/demo module: shows the shape of a data-lookup module other
    actions can call via `context.modules.get("calendar_lookup")` to fetch data
    before continuing (multi-stage actions) - not wired into any other action yet.

    This is not a real Nextcloud Calendar (CalDAV) integration - it just echoes
    the appointment data given to it via params, structured the way a real
    lookup would return it, so a future caller has something concrete to build
    against. Swap in real CalDAV access here once that adapter exists.

    params / return value:
      summary, start, end, location - all optional, passed through as given
    """

    ACTION_NAME: ClassVar[str] = "calendar_lookup"

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "summary": params.get("summary", ""),
            "start": params.get("start"),
            "end": params.get("end"),
            "location": params.get("location", ""),
        }
