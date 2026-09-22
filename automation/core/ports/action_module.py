from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from automation.core.domain.models import DeckEvent
from automation.core.ports.deck_gateway import DeckGatewayPort


@dataclass
class ActionContext:
    """Everything a dynamically loaded action module needs to do its job."""

    event: DeckEvent
    deck: DeckGatewayPort


class WorkflowActionPort(Protocol):
    """Contract every action module must fulfil to be usable from a workflow."""

    ACTION_NAME: str

    def execute(self, context: ActionContext, params: dict[str, Any]) -> None: ...


class ActionModulePort(Protocol):
    """Resolves an action name, as referenced from a workflow YAML's `module:` field,
    to an executable action instance."""

    def get(self, name: str) -> WorkflowActionPort: ...
