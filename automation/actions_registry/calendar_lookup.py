from __future__ import annotations

from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
from automation.core.ports.action_module import ActionContext


class CalendarLookupAction(WorkflowAction):
    """Searches a Nextcloud calendar for the next future occurrence of an
    event whose title contains `title_contains` - recurring events included
    (the series' next actual occurrence is found, not just its own start
    date). See automation/adapters/nextcloud/calendar_gateway.py for how.

    params:
      calendar_id: str - a calendar's CalDAV path, as returned by
        context.calendar.list_calendars() (the website's calendar picker
        uses the same call)
      title_contains: str - substring match against the event's title,
        case-insensitive; empty matches any event

    output:
      title, start, end, location - the matching occurrence, or all null if
        nothing matched
    """

    ACTION_NAME: ClassVar[str] = "calendar_lookup"
    LABEL: ClassVar[str] = "Kalender abfragen"

    def default_input(self) -> dict[str, Any]:
        return {"calendar_id": "", "title_contains": ""}

    def default_output(self) -> dict[str, Any]:
        return {"title": None, "start": None, "end": None, "location": None}

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        if context.calendar is None:
            raise RuntimeError(
                "calendar_lookup: no Nextcloud Calendar connection available for this instance"
            )

        result = context.calendar.find_next_occurrence(
            params["calendar_id"], params.get("title_contains", "")
        )
        return result if result is not None else self.default_output()
