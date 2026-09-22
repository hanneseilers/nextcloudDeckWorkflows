from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from automation.core.domain.models import DeckEvent
from automation.core.ports.deck_gateway import DeckGatewayPort


@dataclass
class ActionContext:
    """Everything a dynamically loaded action module needs to do its job.

    `current_stack_id` starts out as the event's stack and is updated by
    MoveCardAction when it runs, so later actions in the same chain (e.g.
    set_due_date after move_card) address the card's actual current stack
    instead of the one it was in when the event was detected.
    """

    event: DeckEvent
    deck: DeckGatewayPort
    current_stack_id: int = field(init=False)

    def __post_init__(self) -> None:
        self.current_stack_id = self.event.stack_id


class WorkflowActionPort(Protocol):
    """Contract every action module must fulfil to be usable from a workflow."""

    ACTION_NAME: str

    def execute(self, context: ActionContext, params: dict[str, Any]) -> None: ...


class ActionModulePort(Protocol):
    """Resolves an action name, as referenced from a workflow YAML's `module:` field,
    to an executable action instance."""

    def get(self, name: str) -> WorkflowActionPort: ...
