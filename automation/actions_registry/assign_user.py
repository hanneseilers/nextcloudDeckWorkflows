from __future__ import annotations

import logging
from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
from automation.adapters.actions.card_reader import read_current_card
from automation.adapters.actions.user_ids import TYPE_GROUP, parse_user_ids, participant_of
from automation.core.domain.card_data import assigned_participants
from automation.core.ports.action_module import ActionContext

logger = logging.getLogger(__name__)


class AssignUserAction(WorkflowAction):
    """Assigns one or several users - and/or Nextcloud groups - to the
    triggering card. Combine with unassign_user to reassign responsibility
    from one to another.

    A group is written `group:<group id>` and is assigned to the card as a
    whole (Deck shows the group; it does not send notifications for groups) -
    for that the group needs access to the board. Somebody (or some group)
    already assigned is skipped (Deck refuses a second assignment with an
    error), so running this again changes nothing. If assigning one of
    several fails, the others are still assigned and the step then fails
    listing the ones that didn't work.

    params:
      user_id: str | list[str] - Nextcloud user id, `group:<id>` for a group,
        several separated by comma/semicolon, or a list

    output:
      user_ids: list[str] - the assignees requested (all of them are assigned
        afterwards, whether they were before or not)
    """

    ACTION_NAME: ClassVar[str] = "assign_user"
    LABEL: ClassVar[str] = "Zuständige Benutzer zuweisen"
    DESCRIPTION: ClassVar[str] = "Trägt einen oder mehrere Benutzer oder Gruppen als zuständig für die Karte ein."
    PARAM_LABELS: ClassVar[dict[str, str]] = {"user_id": "Benutzer / Gruppen"}
    PARAM_HELP: ClassVar[dict[str, str]] = {
        "user_id": "Mehrere nacheinander auswählen, in der YAML eine Liste oder mit Komma getrennt. Eine Gruppe steht als "
                   "group:<Gruppen-Id> - sie wird als Ganzes zugewiesen und braucht Zugriff auf das Board (Deck benachrichtigt "
                   "Gruppen nicht). Wer schon zugewiesen ist, wird übersprungen."
    }
    OUTPUT_LABELS: ClassVar[dict[str, str]] = {"user_ids": "Zugewiesene Benutzer/Gruppen (Liste)"}

    def default_input(self) -> dict[str, Any]:
        return {"user_id": ""}

    def default_output(self) -> dict[str, Any]:
        return {"user_ids": []}

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        tokens = parse_user_ids(params.get("user_id"))
        if not tokens:
            raise ValueError("assign_user: no user or group given")

        already = assigned_participants(read_current_card(context, "assign_user"))
        failures = []
        for token in tokens:
            if token in already:
                continue
            participant_id, participant_type = participant_of(token)
            try:
                context.deck.assign_user(
                    board_id=context.event.board_id,
                    stack_id=context.current_stack_id,
                    card_id=context.event.card_id,
                    user_id=participant_id,
                    participant_type=participant_type,
                )
            except Exception as exc:  # one failing assignee must not stop the others
                logger.warning("assign_user: could not assign '%s': %s", token, exc)
                hint = ""
                if participant_type == TYPE_GROUP and "not part of the board" in str(exc):
                    hint = " (hat die Gruppe Zugriff auf das Board?)"
                failures.append(f"{token}: {exc}{hint}")
        if failures:
            raise RuntimeError("Could not assign: " + "; ".join(failures))
        return {"user_ids": tokens}
