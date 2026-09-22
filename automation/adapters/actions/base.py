from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from automation.core.ports.action_module import ActionContext


class WorkflowAction(ABC):
    """Base class for dynamically loaded action modules.

    Concrete actions live as standalone .py files under automation/actions_registry/
    and are picked up automatically by adapters.actions.loader.ModuleLoader - no
    registration step required to add a new capability.

    REQUIRES names other ACTION_NAMEs this module needs to call (via
    context.modules.get(...)) in order to work. The loader disables - and logs -
    any action whose declared dependencies aren't all available, instead of
    letting it fail unpredictably the first time it tries to look one up.
    """

    ACTION_NAME: ClassVar[str]
    REQUIRES: ClassVar[tuple[str, ...]] = ()

    @abstractmethod
    def execute(self, context: ActionContext, params: dict[str, Any]) -> Any: ...
