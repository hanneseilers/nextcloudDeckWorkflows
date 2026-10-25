from __future__ import annotations

import logging
from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
from automation.adapters.actions.card_reader import read_current_card
from automation.adapters.actions.user_ids import parse_user_ids
from automation.core.domain.card_data import assigned_user_ids
from automation.core.ports.action_module import ActionContext

logger = logging.getLogger(__name__)


class UnassignUserAction(WorkflowAction):
    """Removes one, several or all assigned users from the triggering card.

    Someone who isn't assigned is skipped, so running this again changes
    nothing. If removing one of several users fails, the others are still
    removed and the step then fails listing the ones that didn't work.

    params:
      user_id: str | list[str] - Nextcloud user id, several ids separated by
        comma/semicolon, or a list of ids (ignored with all_users)
      all_users: bool - remove everybody who is assigned right now

    output:
      user_ids: list[str] - the users that were removed
    """

    ACTION_NAME: ClassVar[str] = "unassign_user"
    LABEL: ClassVar[str] = "Zuständige Benutzer entfernen"
    DESCRIPTION: ClassVar[str] = "Entfernt einen, mehrere oder alle zuständigen Benutzer von der Karte."
    PARAM_LABELS: ClassVar[dict[str, str]] = {"user_id": "Benutzer", "all_users": "Alle Benutzer entfernen"}
    PARAM_HELP: ClassVar[dict[str, str]] = {
        "user_id": "Mehrere Benutzer: im Editor nacheinander auswählen, in der YAML eine Liste oder mit Komma getrennt.",
        "all_users": "An = jeder, der gerade zugewiesen ist, wird entfernt; das Feld Benutzer wird dann nicht gebraucht.",
    }
    OUTPUT_LABELS: ClassVar[dict[str, str]] = {"user_ids": "Entfernte Benutzer (Liste)"}

    def default_input(self) -> dict[str, Any]:
        return {"user_id": "", "all_users": False}

    def default_output(self) -> dict[str, Any]:
        return {"user_ids": []}

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        wanted = parse_user_ids(params.get("user_id"))
        everyone = bool(params.get("all_users"))
        if not everyone and not wanted:
            raise ValueError("unassign_user: no user given (and all_users is off)")

        card = read_current_card(context, "unassign_user")
        if everyone and card is None:
            raise RuntimeError("Could not read who is assigned to the card (see the warning above)")

        if everyone:
            targets = assigned_user_ids(card)
        elif card is not None and "assignedUsers" in card:
            assigned = assigned_user_ids(card)
            targets = [user_id for user_id in wanted if user_id in assigned]
        else:
            targets = wanted  # can't tell who is assigned: just try them

        removed, failures = [], []
        for user_id in targets:
            try:
                context.deck.unassign_user(
                    board_id=context.event.board_id,
                    stack_id=context.current_stack_id,
                    card_id=context.event.card_id,
                    user_id=user_id,
                )
                removed.append(user_id)
            except Exception as exc:  # one failing user must not stop the others
                logger.warning("unassign_user: could not remove '%s': %s", user_id, exc)
                failures.append(f"{user_id}: {exc}")
        if failures:
            raise RuntimeError("Could not remove: " + "; ".join(failures))
        return {"user_ids": removed}
