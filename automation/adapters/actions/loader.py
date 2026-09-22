from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from types import ModuleType

from automation.adapters.actions.base import WorkflowAction
from automation.core.ports.action_module import UnknownActionError

logger = logging.getLogger(__name__)


class ModuleLoader:
    """Implements ActionModulePort. Discovers WorkflowAction subclasses in a plugin
    package and resolves them by their ACTION_NAME. New capabilities are added by
    dropping a .py file into the plugin package - no change to this loader or the
    engine is needed.

    Discovery is resilient by design: a single broken/missing action file, or an
    action whose declared REQUIRES aren't all available, is logged and excluded
    rather than taking down the rest of the registry - this loader has to keep
    working even if only a handful of action modules still exist.
    """

    def __init__(self, package: ModuleType) -> None:
        self._package = package
        self._actions: dict[str, WorkflowAction] | None = None

    def get(self, name: str) -> WorkflowAction:
        self._ensure_discovered()
        try:
            return self._actions[name]
        except KeyError as exc:
            raise UnknownActionError(f"No action module registered as '{name}'") from exc

    def list_names(self) -> list[str]:
        self._ensure_discovered()
        return sorted(self._actions)

    def _ensure_discovered(self) -> None:
        if self._actions is None:
            self._actions = self._discover()

    def _discover(self) -> dict[str, WorkflowAction]:
        actions: dict[str, WorkflowAction] = {}
        for module_info in pkgutil.iter_modules(self._package.__path__):
            try:
                module = importlib.import_module(f"{self._package.__name__}.{module_info.name}")
                for _, obj in inspect.getmembers(module, inspect.isclass):
                    if obj is WorkflowAction or not issubclass(obj, WorkflowAction):
                        continue
                    if inspect.isabstract(obj):
                        continue
                    instance = obj()
                    actions[instance.ACTION_NAME] = instance
            except Exception:
                logger.exception("Skipping action module '%s': failed to load", module_info.name)
        return _drop_modules_with_unmet_requirements(actions)


def _drop_modules_with_unmet_requirements(
    actions: dict[str, WorkflowAction],
) -> dict[str, WorkflowAction]:
    """Removes any action whose REQUIRES aren't all present, then repeats until
    stable so dependency chains (C needs B, B got dropped) cascade correctly."""

    available = dict(actions)
    changed = True
    while changed:
        changed = False
        for name, action in list(available.items()):
            missing = [dep for dep in getattr(action, "REQUIRES", ()) if dep not in available]
            if missing:
                logger.error(
                    "Disabling action '%s': missing required module(s): %s", name, ", ".join(missing)
                )
                del available[name]
                changed = True
    return available
