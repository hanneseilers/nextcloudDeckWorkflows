from __future__ import annotations

from typing import Any, Optional, Protocol

from automation.core.domain.models import DeckEvent


class ActionLinkStorePort(Protocol):
    """Persistence for one-time action links (see create_action_link): a link
    remembers which action to run, with which params, for which card/workflow
    context - the website's link.php claims it when visited, and main.py runs
    it on its next invocation."""

    def create_link(
        self,
        *,
        workflow_id: str,
        event: DeckEvent,
        current_stack_id: int,
        module: str,
        params: dict[str, Any],
        variables: dict[str, Any],
        success_message: str,
        require_confirmation: bool,
        confirm_message: str = "",
        expires_at: Optional[str] = None,
        extra_steps: Optional[list[dict[str, Any]]] = None,
    ) -> str:
        """Stores the link and returns its secret token (only its hash is kept).
        `module`/`params` are the link's first action, `extra_steps` ([{"module",
        "params"}], at most four) the ones that follow it."""
        ...
