from __future__ import annotations

from automation.adapters.actions.simple_card_action import make_simple_card_action

SetDescriptionAction = make_simple_card_action(
    action_name="set_description",
    label="Beschreibung setzen",
    description="Ersetzt die Beschreibung der Karte.",
    param_label="Beschreibung",
    param_name="description",
    default_value="",
    deck_method="set_description",
    doc="""Replaces the content/description of the triggering card.

    params:
      description: str - the new card description (Markdown, as used by Deck)
    """,
)
