from __future__ import annotations

import importlib
import inspect
import pkgutil
from types import ModuleType

from automation.adapters.actions.base import WorkflowAction


class UnknownActionError(KeyError):
    """Raised when a workflow references an action module that isn't registered."""


class ModuleLoader:
    """Implements ActionModulePort. Discovers WorkflowAction subclasses in a plugin
    package and resolves them by their ACTION_NAME. New capabilities are added by
    dropping a .py file into the plugin package - no change to this loader or the
    engine is needed.
    """

    def __init__(self, package: ModuleType) -> None:
        self._package = package
        self._actions: dict[str, WorkflowAction] | None = None

    def get(self, name: str) -> WorkflowAction:
        if self._actions is None:
            self._actions = self._discover()
        try:
            return self._actions[name]
        except KeyError as exc:
            raise UnknownActionError(f"No action module registered as '{name}'") from exc

    def _discover(self) -> dict[str, WorkflowAction]:
        actions: dict[str, WorkflowAction] = {}
        for module_info in pkgutil.iter_modules(self._package.__path__):
            module = importlib.import_module(f"{self._package.__name__}.{module_info.name}")
            for _, obj in inspect.getmembers(module, inspect.isclass):
                if obj is WorkflowAction or not issubclass(obj, WorkflowAction):
                    continue
                if inspect.isabstract(obj):
                    continue
                instance = obj()
                actions[instance.ACTION_NAME] = instance
        return actions
