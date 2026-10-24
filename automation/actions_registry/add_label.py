from __future__ import annotations

from typing import Any, ClassVar, Optional

from automation.adapters.actions.base import WorkflowAction
from automation.core.ports.action_module import ActionContext


class AddLabelAction(WorkflowAction):
    """Adds an existing Deck label (by its numeric id) to the triggering card.

    params:
      label_id: int - id of an existing label on the card's board

    output:
      label_id: int - the label that was added
      label_name: str | None - its name, looked up among the board's labels
        (None if it can't be found - the label is added either way)
    """

    ACTION_NAME: ClassVar[str] = "add_label"
    LABEL: ClassVar[str] = "Label hinzufügen"
    DESCRIPTION: ClassVar[str] = "Fügt der Karte ein vorhandenes Label des Boards hinzu."
    PARAM_LABELS: ClassVar[dict[str, str]] = {"label_id": "Label"}
    OUTPUT_LABELS: ClassVar[dict[str, str]] = {"label_id": "Label-Id", "label_name": "Label-Name"}

    def default_input(self) -> dict[str, Any]:
        return {"label_id": 0}

    def default_output(self) -> dict[str, Any]:
        return {"label_id": 0, "label_name": ""}

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        label_id = params["label_id"]
        context.deck.add_label(
            board_id=context.event.board_id,
            stack_id=context.current_stack_id,
            card_id=context.event.card_id,
            label_id=label_id,
        )
        return {"label_id": label_id, "label_name": _label_name(context, label_id)}


def _label_name(context: ActionContext, label_id: Any) -> Optional[str]:
    try:
        labels = context.deck.list_labels(context.event.board_id)
    except Exception:
        return None  # the label was added; only its name is unknown
    for label in labels:
        if str(label.get("id")) == str(label_id):
            return label.get("title")
    return None
