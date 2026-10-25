from __future__ import annotations

import logging
from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
from automation.adapters.actions.card_reader import read_current_card
from automation.adapters.actions.user_ids import parse_user_ids
from automation.core.domain.card_data import assigned_user_ids
from automation.core.ports.action_module import ActionContext

logger = logging.getLogger(__name__)


class AssignUserAction(WorkflowAction):
    """Assigns one or several users to the triggering card. Combine with
    unassign_user to reassign responsibility from one user to another.

    A user who is already assigned is skipped (Deck refuses a second
    assignment with an error), so running this again changes nothing. If
    assigning one of several users fails, the others are still assigned and
    the step then fails listing the ones that didn't work.

    params:
      user_id: str | list[str] - Nextcloud user id, several ids separated by
        comma/semicolon, or a list of ids

    output:
      user_ids: list[str] - the users requested (all of them are assigned
        afterwards, whether they were before or not)
    """

    ACTION_NAME: ClassVar[str] = "assign_user"
    LABEL: ClassVar[str] = "Zuständige Benutzer zuweisen"
    DESCRIPTION: ClassVar[str] = "Trägt einen oder mehrere Benutzer als zuständig für die Karte ein."
    PARAM_LABELS: ClassVar[dict[str, str]] = {"user_id": "Benutzer"}
    PARAM_HELP: ClassVar[dict[str, str]] = {
        "user_id": "Mehrere Benutzer: im Editor nacheinander auswählen, in der YAML eine Liste oder mit Komma getrennt. "
                   "Wer schon zugewiesen ist, wird übersprungen."
    }
    OUTPUT_LABELS: ClassVar[dict[str, str]] = {"user_ids": "Zugewiesene Benutzer (Liste)"}

    def default_input(self) -> dict[str, Any]:
        return {"user_id": ""}

    def default_output(self) -> dict[str, Any]:
        return {"user_ids": []}

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        user_ids = parse_user_ids(params.get("user_id"))
        if not user_ids:
            raise ValueError("assign_user: no user given")

        already = assigned_user_ids(read_current_card(context, "assign_user"))
        failures = []
        for user_id in user_ids:
            if user_id in already:
                continue
            try:
                context.deck.assign_user(
                    board_id=context.event.board_id,
                    stack_id=context.current_stack_id,
                    card_id=context.event.card_id,
                    user_id=user_id,
                )
            except Exception as exc:  # one failing user must not stop the others
                logger.warning("assign_user: could not assign '%s': %s", user_id, exc)
                failures.append(f"{user_id}: {exc}")
        if failures:
            raise RuntimeError("Could not assign: " + "; ".join(failures))
        return {"user_ids": user_ids}
