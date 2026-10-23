from __future__ import annotations

from typing import Any, ClassVar, Optional

from automation.adapters.actions.base import WorkflowAction
from automation.core.ports.action_module import ActionContext


# A copy of a copy of a copy ... - beyond this, copy_card refuses: that is a
# loop between workflows (W1 copies X->Y, W2 copies Y->X), not a real use.
MAX_COPY_DEPTH = 5


class CopyCardAction(WorkflowAction):
    """Copies the triggering card into a column of another board (or another
    column of the same board) on the same Nextcloud instance.

    The copy is a brand-new card carrying only a title and a description:
    assigned users, labels, due date, comments, attachments etc. are NOT
    copied. By default the title/description are those of the original (as
    they are right now, including changes made by earlier steps of the same
    run); a non-empty `title`/`description` param replaces them in the copy.
    The original card is left untouched.

    Note: the new card is a normal new card on the target board, so a
    workflow triggered by "Karte erstellt" there will fire for it too - except
    the workflow that made the copy (it never reacts to its own copies, so
    copying into the column it watches doesn't loop). A copy of a copy is
    allowed up to MAX_COPY_DEPTH levels; deeper, copy_card fails with an
    error, which cuts off a copy loop between two workflows.

    The Deck API calls behind this are not verified against a live Nextcloud
    instance (no such access was available while building this).

    params:
      target_board_id: int - board to copy into
      target_stack_id: int - column (of that board) to copy into
      title: str (optional) - title for the copy; empty = keep the original's
      description: str (optional) - description for the copy; empty = keep
        the original's

    output:
      card_id: int - id of the new card
      board_id: int - board it was created on
      stack_id: int - column it was created in
    """

    ACTION_NAME: ClassVar[str] = "copy_card"
    LABEL: ClassVar[str] = "Karte kopieren"

    def default_input(self) -> dict[str, Any]:
        return {"target_board_id": 0, "target_stack_id": 0, "title": "", "description": ""}

    def default_output(self) -> dict[str, Any]:
        return {"card_id": 0, "board_id": 0, "stack_id": 0}

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
        target_board_id = int(params["target_board_id"])
        target_stack_id = int(params["target_stack_id"])

        original = _find_card(context) or dict(context.event.card)
        title = params.get("title") or original.get("title") or ""
        description = params.get("description") or original.get("description") or ""
        if not title:
            raise ValueError("copy_card: the card has no title to copy and none was given")

        depth = 1
        if context.copy_store is not None:
            source = context.copy_store.copy_info(context.event.instance, context.event.board_id, context.event.card_id)
            depth = (source[1] if source else 0) + 1
            if depth > MAX_COPY_DEPTH:
                raise RuntimeError(
                    f"copy_card: this card is already a copy {depth - 1} levels deep - "
                    "stopping what looks like a copy loop between workflows"
                )

        created = context.deck.create_card(
            board_id=target_board_id, stack_id=target_stack_id, title=title, description=description
        )
        if context.copy_store is not None and created.get("id") is not None:
            context.copy_store.record_copy(
                context.event.instance, target_board_id, created["id"], context.workflow_id, depth
            )
        return {"card_id": created.get("id"), "board_id": target_board_id, "stack_id": target_stack_id}


def _find_card(context: ActionContext) -> Optional[dict[str, Any]]:
    for card in context.deck.list_cards(context.event.board_id, context.current_stack_id):
        if card.get("id") == context.event.card_id:
            return card
    return None
