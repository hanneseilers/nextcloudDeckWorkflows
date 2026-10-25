from __future__ import annotations

from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
from automation.core.ports.action_module import ActionContext


class RevokeActionLinksAction(WorkflowAction):
    """Switches off the card's still unused one-time links (see create_action_link).

    Typical use: two links per card, "annehmen" and "ablehnen" - add this
    action to the actions of each link (after the real one), so using one
    link makes the other one invalid. It also works as an ordinary step.

    Only links that are still open are affected: the link currently being run
    is already used up, and a link somebody visited a moment ago keeps its
    outcome. A revoked link shows the same "ungültig" page as a used one.

    params:
      all_workflows: bool - false (default): only the links this workflow
        created for the card; true: every workflow's links for the card

    output:
      revoked: int - how many links were switched off
    """

    ACTION_NAME: ClassVar[str] = "revoke_action_links"
    LABEL: ClassVar[str] = "Einmal-Links der Karte deaktivieren"
    DESCRIPTION: ClassVar[str] = "Macht alle noch unbenutzten Einmal-Links dieser Karte ungültig."
    PARAM_LABELS: ClassVar[dict[str, str]] = {"all_workflows": "Auch Links anderer Workflows"}
    PARAM_HELP: ClassVar[dict[str, str]] = {"all_workflows": "Aus = nur Links, die dieser Workflow für die Karte erstellt hat. Tipp: als Aktion in jeden Einmal-Link nach der eigentlichen Aktion einbauen, dann macht der Aufruf eines Links die übrigen ungültig."}
    OUTPUT_LABELS: ClassVar[dict[str, str]] = {"revoked": "Anzahl deaktivierter Links"}

    def default_input(self) -> dict[str, Any]:
        return {"all_workflows": False}

    def default_output(self) -> dict[str, Any]:
        return {"revoked": 0}

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        if context.link_store is None:
            raise RuntimeError("revoke_action_links: no link store available for this run")
        event = context.event
        count = context.link_store.revoke_links(
            instance=event.instance, board_id=event.board_id, card_id=event.card_id,
            workflow_id=None if params.get("all_workflows") else context.workflow_id,
        )
        return {"revoked": count}
