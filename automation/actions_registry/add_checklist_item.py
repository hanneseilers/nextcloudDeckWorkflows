from __future__ import annotations

from typing import Any, ClassVar, Optional

from automation.adapters.actions.base import WorkflowAction
from automation.core.ports.action_module import ActionContext


class AddChecklistItemAction(WorkflowAction):
    """Adds a checklist item to the triggering card.

    Nextcloud Deck has no separate checklist-item API - a card's checklist
    is just Markdown checkbox syntax (`- [ ] text`) inside its own
    `description`, parsed and rendered by the Deck UI. This reads the
    card's current description, appends one such line, and writes the
    whole thing back via set_description - not verified against a live
    Nextcloud instance (no such access was available while building this),
    but matches Deck's documented Markdown checklist convention.

    params:
      text: str - the checklist item's text

    output:
      description: str - the card's new, full description (including the
        added line) - useful if a later step wants to show/log it
    """

    ACTION_NAME: ClassVar[str] = "add_checklist_item"

    def default_input(self) -> dict[str, Any]:
        return {"text": ""}

    def default_output(self) -> dict[str, Any]:
        return {"description": ""}

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        text = params["text"]
        card = _find_card(context, context.event.board_id, context.current_stack_id, context.event.card_id)
        current_description = (card or {}).get("description") or ""

        separator = "\n" if current_description and not current_description.endswith("\n") else ""
        new_description = f"{current_description}{separator}- [ ] {text}\n"

        context.deck.set_description(
            board_id=context.event.board_id,
            stack_id=context.current_stack_id,
            card_id=context.event.card_id,
            description=new_description,
        )
        return {"description": new_description}


def _find_card(context: ActionContext, board_id: int, stack_id: int, card_id: int) -> Optional[dict[str, Any]]:
    for card in context.deck.list_cards(board_id, stack_id):
        if card.get("id") == card_id:
            return card
    return None
