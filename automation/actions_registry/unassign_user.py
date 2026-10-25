from __future__ import annotations

import logging
from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
from automation.adapters.actions.card_reader import read_current_card
from automation.adapters.actions.user_ids import parse_user_ids, participant_of
from automation.core.domain.card_data import assigned_participants
from automation.core.ports.action_module import ActionContext

logger = logging.getLogger(__name__)


class UnassignUserAction(WorkflowAction):
    """Removes one, several or all assigned users and groups from the
    triggering card.

    A group is written `group:<group id>` (see assign_user). Someone who isn't
    assigned is skipped, so running this again changes nothing. If removing
    one of several fails, the others are still removed and the step then
    fails listing the ones that didn't work.

    params:
      user_id: str | list[str] - Nextcloud user id, `group:<id>` for a group,
        several separated by comma/semicolon, or a list (ignored with all_users)
      all_users: bool - remove everybody who is assigned right now (users and
        groups)

    output:
      user_ids: list[str] - the assignees that were removed
    """

    ACTION_NAME: ClassVar[str] = "unassign_user"
    LABEL: ClassVar[str] = "Zuständige Benutzer entfernen"
    DESCRIPTION: ClassVar[str] = "Entfernt einen, mehrere oder alle zuständigen Benutzer und Gruppen von der Karte."
    PARAM_LABELS: ClassVar[dict[str, str]] = {"user_id": "Benutzer / Gruppen", "all_users": "Alle entfernen (Benutzer und Gruppen)"}
    PARAM_HELP: ClassVar[dict[str, str]] = {
        "user_id": "Mehrere nacheinander auswählen, in der YAML eine Liste oder mit Komma getrennt. Eine Gruppe steht als group:<Gruppen-Id>.",
        "all_users": "An = jeder Benutzer und jede Gruppe, die gerade zugewiesen ist, wird entfernt; das Feld Benutzer wird dann nicht gebraucht.",
    }
    OUTPUT_LABELS: ClassVar[dict[str, str]] = {"user_ids": "Entfernte Benutzer/Gruppen (Liste)"}

    def default_input(self) -> dict[str, Any]:
        return {"user_id": "", "all_users": False}

    def default_output(self) -> dict[str, Any]:
        return {"user_ids": []}

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        wanted = parse_user_ids(params.get("user_id"))
        everyone = bool(params.get("all_users"))
        if not everyone and not wanted:
            raise ValueError("unassign_user: no user or group given (and all_users is off)")

        card = read_current_card(context, "unassign_user")
        if everyone and card is None:
            raise RuntimeError("Could not read who is assigned to the card (see the warning above)")

        if everyone:
            targets = assigned_participants(card)
        elif card is not None and "assignedUsers" in card:
            assigned = assigned_participants(card)
            targets = [token for token in wanted if token in assigned]
        else:
            targets = wanted  # can't tell who is assigned: just try them

        removed, failures = [], []
        for token in targets:
            participant_id, participant_type = participant_of(token)
            try:
                context.deck.unassign_user(
                    board_id=context.event.board_id,
                    stack_id=context.current_stack_id,
                    card_id=context.event.card_id,
                    user_id=participant_id,
                    participant_type=participant_type,
                )
                removed.append(token)
            except Exception as exc:  # one failing assignee must not stop the others
                logger.warning("unassign_user: could not remove '%s': %s", token, exc)
                failures.append(f"{token}: {exc}")
        if failures:
            raise RuntimeError("Could not remove: " + "; ".join(failures))
        return {"user_ids": removed}
