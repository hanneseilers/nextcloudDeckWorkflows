from __future__ import annotations

from automation.adapters.actions.simple_card_action import make_simple_card_action

SetTitleAction = make_simple_card_action(
    action_name="set_title",
    label="Titel setzen",
    description="Ändert den Titel der Karte.",
    param_label="Titel",
    param_name="title",
    default_value="",
    output_label="Titel",
    deck_method="set_title",
    doc="""Renames the triggering card (changes its title).

    params:
      title: str - the new card title

    output:
      title: str - the title that was set
    """,
)
