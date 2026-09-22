"""Domain model for the workflow automation core. No I/O, no framework dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class EventType(str, Enum):
    CARD_CREATED = "card_created"
    CARD_MOVED = "card_moved"
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


@dataclass(frozen=True)
class Trigger:
    event_type: EventType
    stack_id: Optional[int] = None


@dataclass(frozen=True)
class ActionStep:
    """One step of a workflow's action chain.

    `id` lets a *later* step's `params` reference this step's output (see
    automation.core.domain.engine._resolve_ref) - e.g. {"$ref": "lookup.summary"}
    to use the `summary` field of the step with id "lookup". Optional: falls
    back to the step's position in the list if left empty, so steps that don't
    need to be referenced don't need one.
    """

    module: str
    id: str = ""
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Workflow:
    id: str
    name: str
    instance: str
    board_id: int
    trigger: Trigger
    actions: tuple[ActionStep, ...]
    enabled: bool = True

    def matches(self, event: DeckEvent) -> bool:
        if not self.enabled:
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
