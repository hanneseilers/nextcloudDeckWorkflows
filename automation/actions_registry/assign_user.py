from __future__ import annotations

from automation.adapters.actions.simple_card_action import make_simple_card_action

AssignUserAction = make_simple_card_action(
    action_name="assign_user",
    label="Zuständigen Benutzer zuweisen",
    param_name="user_id",
    default_value="",
    deck_method="assign_user",
    doc="""Assigns a user as responsible for the triggering card. Combine with
    unassign_user to reassign responsibility from one user to another.

    params:
      user_id: str - Nextcloud user id to assign
    """,
)
