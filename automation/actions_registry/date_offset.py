from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
from automation.core.ports.action_module import ActionContext


class DateOffsetAction(WorkflowAction):
    """Computes a date: a base date plus/minus a number of days. Useful for
    e.g. setting a due date a few days from now (chain with set_due_date via
    {"$ref": "<this step's id>.date"}).

    params:
      base: str | None - ISO-8601 timestamp to start from; omitted/None means
        "now" (UTC)
      days: int - added to base; negative to go backwards

    output:
      date: str - the computed ISO-8601 timestamp
    """

    ACTION_NAME: ClassVar[str] = "date_offset"
    LABEL: ClassVar[str] = "Datum verschieben"

    def default_input(self) -> dict[str, Any]:
        return {"base": None, "days": 0}

    def default_output(self) -> dict[str, Any]:
        return {"date": None}

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        base = params.get("base")
        start = datetime.fromisoformat(base) if base else datetime.now(timezone.utc)
        result = start + timedelta(days=params.get("days", 0))
        return {"date": result.isoformat()}
