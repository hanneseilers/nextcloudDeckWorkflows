from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Iterable, Protocol

from automation.core.domain.models import DeckEvent
from automation.core.ports.deck_gateway import DeckGatewayPort


class UnknownActionError(KeyError):
    """Raised when a workflow, or another action module, references an action name
    that isn't registered - either no such file exists, or it was disabled because
    a declared dependency (see WorkflowActionPort.REQUIRES) wasn't available."""


@dataclass
class ActionContext:
    """Everything a dynamically loaded action module needs to do its job.

    `modules` is the same registry the engine resolves workflow steps from - an
    action can call `context.modules.get("other_action")` and run it directly to
    reuse its logic and its return value (e.g. fetch data from a lookup module
    before continuing), enabling multi-stage actions without any special-cased
    mechanism beyond this one port.

    `current_stack_id` starts out as the event's stack and is updated by
    MoveCardAction when it runs, so later actions in the same chain (e.g.
    set_due_date after move_card) address the card's actual current stack
    instead of the one it was in when the event was detected.
    """

    event: DeckEvent
    deck: DeckGatewayPort
    modules: "ActionModulePort"
    current_stack_id: int = field(init=False)

    def __post_init__(self) -> None:
        self.current_stack_id = self.event.stack_id


class WorkflowActionPort(Protocol):
    """Contract every action module must fulfil to be usable from a workflow.

    Input and output are both plain JSON objects (dict[str, Any] of JSON-safe
    values - str/int/float/bool/None/list/dict, same as anything loaded from a
    workflow's YAML). `default_input`/`default_output` document a module's
    expected shape as an example object; a workflow maps another step's output
    field into a param via {"$ref": "<step_id>.<field>"} (see
    automation.core.domain.engine._resolve_params).
    """

    ACTION_NAME: str
    REQUIRES: ClassVar[tuple[str, ...]]

    def default_input(self) -> dict[str, Any]: ...

    def default_output(self) -> dict[str, Any]: ...

    def execute(self, context: ActionContext, params: dict[str, Any]) -> dict[str, Any]: ...


class ActionModulePort(Protocol):
    """Resolves an action name, as referenced from a workflow YAML's `module:` field
    or from another action's own code, to an executable action instance."""

    def get(self, name: str) -> WorkflowActionPort: ...

    def list_names(self) -> Iterable[str]: ...
