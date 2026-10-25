"""Shared by the actions that look at the card before changing it (assign_user,
unassign_user, remove_label): Deck refuses to assign a user twice or to remove
a label the card doesn't have, so they check first."""

from __future__ import annotations

import logging
from typing import Any, Optional

from automation.core.ports.action_module import ActionContext

logger = logging.getLogger(__name__)


def read_current_card(context: ActionContext, action: str) -> Optional[dict[str, Any]]:
    """The triggering card as Deck returns it right now, or None - with a
    warning, never an exception - if it can't be read: the action then simply
    tries what it was asked to do, which is what it did before it looked."""

    try:
        return context.deck.get_card(
            board_id=context.event.board_id, stack_id=context.current_stack_id, card_id=context.event.card_id
        )
    except Exception as exc:
        logger.warning("%s: could not read the card, going ahead without checking it first: %s", action, exc)
        return None
