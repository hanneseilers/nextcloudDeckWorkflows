from __future__ import annotations

from automation.adapters.actions.simple_card_action import make_simple_card_action

SetDueDateAction = make_simple_card_action(
    action_name="set_due_date",
    label="Fälligkeitsdatum setzen",
    description="Setzt (oder löscht, wenn leer) das Fälligkeitsdatum der Karte.",
    param_label="Fälligkeitsdatum",
    param_name="due_date",
    default_value=None,
    deck_method="set_due_date",
    optional=True,
    doc="""Sets (or clears) the due date of the triggering card.

    params:
      due_date: str | None - ISO-8601 timestamp (e.g. "2026-01-31T00:00:00+00:00"),
                              or null/omitted to clear the due date
    """,
)
