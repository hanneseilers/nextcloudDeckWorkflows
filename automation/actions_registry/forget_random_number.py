from __future__ import annotations

from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
from automation.core.ports.action_module import ActionContext


class ForgetRandomNumberAction(WorkflowAction):
    """Removes a number from generate_random_number's "already generated"
    list, so it becomes available to generate again - e.g. because whatever
    was using it (a card, a ticket) was deleted. Pass the exact string
    generate_random_number produced (typically via {"$ref": "<step_id>.number"}
    from that step, possibly carried through other modules/card fields in
    between) - the list is matched by exact text, including leading zeros,
    not by numeric value.

    Removing a number that was never in the list (wrong list_name, already
    removed, or never saved in the first place) is a no-op, not an error -
    this action is naturally idempotent.

    params:
      list_name: str - same list generate_random_number used (default "default")
      number: str - the number to remove

    output: (none)
    """

    ACTION_NAME: ClassVar[str] = "forget_random_number"
    LABEL: ClassVar[str] = "Zufallszahl freigeben"

    def default_input(self) -> dict[str, Any]:
        return {"list_name": "default", "number": ""}

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        if context.sequence_store is None:
            raise RuntimeError("forget_random_number: no sequence store available for this run")

        list_name = str(params.get("list_name") or "default")
        context.sequence_store.remove_number(list_name, str(params["number"]))
        return {}
