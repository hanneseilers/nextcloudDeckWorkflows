from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from automation.core.ports.action_module import ActionContext


class WorkflowAction(ABC):
    """Base class for dynamically loaded action modules.

    Concrete actions live as standalone .py files under automation/actions_registry/
    and are picked up automatically by adapters.actions.loader.ModuleLoader - no
    registration step required to add a new capability.
    """

    ACTION_NAME: ClassVar[str]

    @abstractmethod
    def execute(self, context: ActionContext, params: dict[str, Any]) -> None: ...
