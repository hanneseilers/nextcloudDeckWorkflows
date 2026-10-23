from __future__ import annotations

from automation.adapters.actions.simple_card_action import make_simple_card_action

UnassignUserAction = make_simple_card_action(
    action_name="unassign_user",
    label="Zuständigen Benutzer entfernen",
    description="Entfernt einen zuständigen Benutzer von der Karte.",
    param_label="Benutzer",
    param_name="user_id",
    default_value="",
    deck_method="unassign_user",
    doc="""Removes a user's assignment from the triggering card.

    params:
      user_id: str - Nextcloud user id to unassign
    """,
)
