from __future__ import annotations

from typing import Any, ClassVar, Optional

from automation.adapters.actions.base import WorkflowAction
from automation.adapters.actions.card_reader import read_current_card
from automation.core.domain.card_data import card_label_ids
from automation.core.ports.action_module import ActionContext


class RemoveLabelAction(WorkflowAction):
    """Removes a label (by its numeric id) from the triggering card - the
    counterpart of add_label.

    A label the card doesn't have is skipped (Deck would refuse it with an
    error), so running this again changes nothing.

    params:
      label_id: int - id of a label of the card's board

    output:
      label_id: int - the label
      label_name: str | None - its name, looked up among the board's labels
        (None if it can't be found)
      removed: bool - false if the card didn't have the label
    """

    ACTION_NAME: ClassVar[str] = "remove_label"
    LABEL: ClassVar[str] = "Label entfernen"
    DESCRIPTION: ClassVar[str] = "Entfernt ein Label von der Karte (hat sie es nicht, passiert nichts)."
    PARAM_LABELS: ClassVar[dict[str, str]] = {"label_id": "Label"}
    OUTPUT_LABELS: ClassVar[dict[str, str]] = {
        "label_id": "Label-Id", "label_name": "Label-Name", "removed": "Entfernt (nein = hatte die Karte nicht)",
    }

    def default_input(self) -> dict[str, Any]:
        return {"label_id": 0}

    def default_output(self) -> dict[str, Any]:
        return {"label_id": 0, "label_name": "", "removed": True}

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        label_id = params["label_id"]
        name = _label_name(context, label_id)

        card = read_current_card(context, "remove_label")
        if card is not None and "labels" in card and str(label_id) not in card_label_ids(card):
            return {"label_id": label_id, "label_name": name, "removed": False}

        context.deck.remove_label(
            board_id=context.event.board_id,
            stack_id=context.current_stack_id,
            card_id=context.event.card_id,
            label_id=label_id,
        )
        return {"label_id": label_id, "label_name": name, "removed": True}


def _label_name(context: ActionContext, label_id: Any) -> Optional[str]:
    try:
        labels = context.deck.list_labels(context.event.board_id)
    except Exception:
        return None
    for label in labels:
        if str(label.get("id")) == str(label_id):
            return label.get("title")
    return None
