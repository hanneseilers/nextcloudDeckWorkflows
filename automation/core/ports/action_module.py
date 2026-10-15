from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Iterable, Optional, Protocol

from automation.core.domain.models import DeckEvent
from automation.core.ports.calendar_gateway import CalendarGatewayPort
from automation.core.ports.deck_gateway import DeckGatewayPort
from automation.core.ports.sequence_store import SequenceStorePort


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

    `variables` is the workflow run's shared global-variable store, written to
    by SetVariableAction under a workflow-chosen name and shared with the
    engine (see WorkflowEngine._run, which exposes the same dict as
    outputs_by_step["vars"] for {"$ref": "vars.<name>"}) and with any action
    that substitutes $placeholders in free text (send_email, add_comment).

    `calendar` is the CalDAV connection for this event's Nextcloud instance -
    None where it wasn't set up (dry-run, most tests), in which case
    calendar_lookup raises a clear error rather than crashing with an
    AttributeError, caught like any other action's error.

    `sequence_store` backs generate_random_number/forget_random_number's
    "already generated" lists - one store shared across all instances/boards
    (unlike `calendar`, nothing here is Nextcloud-instance-specific). None in
    the same situations as `calendar` (dry-run, most tests), where those two
    actions raise a clear error instead of crashing.
    """

    event: DeckEvent
    deck: DeckGatewayPort
    modules: "ActionModulePort"
    variables: dict[str, Any] = field(default_factory=dict)
    calendar: Optional[CalendarGatewayPort] = None
    sequence_store: Optional[SequenceStorePort] = None
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
