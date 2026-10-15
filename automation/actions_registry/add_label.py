from __future__ import annotations

from automation.adapters.actions.simple_card_action import make_simple_card_action

AddLabelAction = make_simple_card_action(
    action_name="add_label",
    label="Label hinzufügen",
    param_name="label_id",
    default_value=0,
    deck_method="add_label",
    doc="""Adds an existing Deck label (by its numeric id) to the triggering card.

    params:
      label_id: int - id of an existing label on the card's board
    """,
)
