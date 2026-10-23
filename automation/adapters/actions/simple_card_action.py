from __future__ import annotations

from typing import Any, ClassVar

from automation.adapters.actions.base import WorkflowAction
from automation.core.ports.action_module import ActionContext


def make_simple_card_action(
    *,
    action_name: str,
    label: str,
    description: str,
    param_label: str,
    param_name: str,
    default_value: Any,
    deck_method: str,
    optional: bool = False,
    doc: str,
) -> type[WorkflowAction]:
    """Builds a WorkflowAction subclass for the common "write one field of the
    triggering card via one DeckGatewayPort method" shape - set_title,
    set_description, set_due_date, add_label, assign_user and unassign_user
    are all exactly this pattern, differing only in which field/method.

    `deck_method` is looked up on `context.deck` at call time (not bound
    here), since the deck gateway differs per run. `optional=True` (only
    set_due_date needs this) reads the param with .get() instead of [...],
    so a missing/None value is tolerated instead of raising KeyError.
    """

    class _SimpleCardAction(WorkflowAction):
        ACTION_NAME: ClassVar[str] = action_name
        LABEL: ClassVar[str] = label
        DESCRIPTION: ClassVar[str] = description
        PARAM_LABELS: ClassVar[dict[str, str]] = {param_name: param_label}

        def default_input(self) -> dict[str, Any]:
            return {param_name: default_value}

        def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]:
            value = params.get(param_name) if optional else params[param_name]
            getattr(context.deck, deck_method)(
                board_id=context.event.board_id,
                stack_id=context.current_stack_id,
                card_id=context.event.card_id,
                **{param_name: value},
            )
            return {}

    _SimpleCardAction.__doc__ = doc
    _SimpleCardAction.__name__ = action_name
    _SimpleCardAction.__qualname__ = action_name
    return _SimpleCardAction
