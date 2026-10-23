"""Domain model for the workflow automation core. No I/O, no framework dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Union


class EventType(str, Enum):
    CARD_CREATED = "card_created"
    CARD_MOVED = "card_moved"
    # Fired alongside CARD_UPDATED (not instead of it) whenever the specific
    # field changed - CARD_UPDATED keeps firing on any change, as before, so
    # an existing workflow watching it is unaffected by these more specific
    # additions. See PollingEventSource._diff.
    CARD_ASSIGNED = "card_assigned"
    CARD_DUE_DATE_CHANGED = "card_due_date_changed"
    CARD_DESCRIPTION_CHANGED = "card_description_changed"
    CARD_LABEL_CHANGED = "card_label_changed"
    CARD_UPDATED = "card_updated"
    CARD_DELETED = "card_deleted"


@dataclass(frozen=True)
class DeckEvent:
    """A single change detected on a Nextcloud Deck board."""

    instance: str
    board_id: int
    event_type: EventType
    card_id: int
    stack_id: int
    previous_stack_id: Optional[int] = None
    card: dict = field(default_factory=dict)
    # The card's lastModified as of the previous poll (None for a new card) -
    # identifies "this exact change" again when a killed run is repeated.
    previous_last_modified: Optional[int] = None


@dataclass(frozen=True)
class ScheduleTrigger:
    """A time-based trigger, independent of any Deck event - "every day at
    09:00" or "every Monday at 09:00". Interpreted in the server's local
    time, same as a cron expression would be.

    `weekdays` is ISO weekday numbers (1=Monday..7=Sunday); None/empty means
    every day. A workflow using this should stick to actions that don't need
    a real triggering card (send_email, log_action, generate_random_number,
    calculate, ...) - see main.py::_process_schedules, which runs it against
    a synthetic, card-less event.
    """

    time: str  # "HH:MM"
    weekdays: Optional[tuple[int, ...]] = None


@dataclass(frozen=True)
class Trigger:
    # Exactly one of event_type or schedule is set - see
    # YamlWorkflowRepository._parse for which YAML shape produces which.
    event_type: Optional[EventType] = None
    stack_id: Optional[int] = None
    schedule: Optional[ScheduleTrigger] = None


@dataclass(frozen=True)
class ActionStep:
    """One step of a workflow's action chain.

    `id` lets a *later* step's `params` reference this step's output (see
    automation.core.domain.engine._resolve_ref) - e.g. {"$ref": "lookup.summary"}
    to use the `summary` field of the step with id "lookup". Optional: falls
    back to the step's position in the run if left empty, so steps that don't
    need to be referenced don't need one.
    """

    module: str
    id: str = ""
    params: dict = field(default_factory=dict)


class ComparisonOp(str, Enum):
    """Operators an IfStep's condition can use. String-named rather than raw
    Python operators so a condition serializes cleanly to/from YAML and can't
    smuggle in arbitrary code - see WorkflowEngine._evaluate_condition."""

    EQ = "eq"
    NE = "ne"
    LT = "lt"
    GT = "gt"
    CONTAINS = "contains"
    BEGINS_WITH = "beginswith"
    ENDS_WITH = "endswith"


@dataclass(frozen=True)
class Condition:
    """`left <op> right`. Each side is a literal or {"$ref": ...}, resolved
    the same way an ActionStep's params are (see
    automation.core.domain.engine._resolve_params) before comparing."""

    left: Any
    op: ComparisonOp
    right: Any


@dataclass(frozen=True)
class IfStep:
    """A branching step: evaluates `condition` and runs `then_steps` if it's
    true, `else_steps` if it's false. Each branch is itself a list of
    ActionStep/IfStep, so branches can contain several steps and nest -
    see WorkflowEngine._run_steps."""

    condition: Condition
    then_steps: tuple["WorkflowStep", ...] = ()
    else_steps: tuple["WorkflowStep", ...] = ()


WorkflowStep = Union[ActionStep, IfStep]


@dataclass(frozen=True)
class Workflow:
    id: str
    name: str
    instance: str
    board_id: int
    trigger: Trigger
    actions: tuple[WorkflowStep, ...]
    enabled: bool = True

    def matches(self, event: DeckEvent) -> bool:
        if not self.enabled or self.trigger.event_type is None:
            # A schedule-triggered workflow (event_type is None) never fires
            # off a Deck event - see main.py::_process_schedules instead.
            return False
        if self.instance != event.instance or self.board_id != event.board_id:
            return False
        if self.trigger.event_type != event.event_type:
            return False
        if self.trigger.stack_id is not None and self.trigger.stack_id != event.stack_id:
            return False
        return True


@dataclass
class ActionResult:
    module: str
    success: bool
    error: Optional[str] = None


@dataclass
class ExecutionResult:
    workflow_id: str
    event: DeckEvent
    action_results: list = field(default_factory=list)

    @property
    def success(self) -> bool:
        return all(r.success for r in self.action_results)
