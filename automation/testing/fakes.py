"""In-memory fakes for the core's ports, used by unit tests and by `main.py --dry-run`.

They let the WorkflowEngine and PollingEventSource be exercised without any real
network, filesystem or database access - the main benefit of the hexagonal split.
"""

from __future__ import annotations

from typing import Any, Optional

from automation.core.domain.models import ExecutionResult, Workflow


class InMemoryDeckGateway:
    """Fake DeckGatewayPort. `stacks` maps board_id -> list of stack dicts
    ({"id": ..., "cards": [{"id": ..., "lastModified": ...}, ...]})."""

    def __init__(self, stacks: Optional[dict[int, list[dict[str, Any]]]] = None) -> None:
        self.stacks: dict[int, list[dict[str, Any]]] = stacks or {}
        self.calls: list[tuple] = []

    def list_boards(self) -> list[dict[str, Any]]:
        return [{"id": board_id} for board_id in self.stacks]

    def list_stacks(self, board_id: int) -> list[dict[str, Any]]:
        return self.stacks.get(board_id, [])

    def list_cards(self, board_id: int, stack_id: int) -> list[dict[str, Any]]:
        for stack in self.list_stacks(board_id):
            if stack["id"] == stack_id:
                return stack.get("cards", [])
        return []

    def add_label(self, board_id: int, card_id: int, label_id: int) -> None:
        self.calls.append(("add_label", board_id, card_id, label_id))

    def move_card(self, board_id: int, card_id: int, target_stack_id: int, order: int = 0) -> None:
        self.calls.append(("move_card", board_id, card_id, target_stack_id, order))

    def add_comment(self, card_id: int, message: str) -> None:
        self.calls.append(("add_comment", card_id, message))


class InMemoryWorkflowRepository:
    def __init__(self, workflows: list[Workflow]) -> None:
        self._workflows = {wf.id: wf for wf in workflows}

    def list_enabled(self) -> list[Workflow]:
        return [wf for wf in self._workflows.values() if wf.enabled]

    def get(self, workflow_id: str) -> Optional[Workflow]:
        return self._workflows.get(workflow_id)

    def save(self, workflow: Workflow) -> None:
        self._workflows[workflow.id] = workflow

    def delete(self, workflow_id: str) -> None:
        self._workflows.pop(workflow_id, None)


class InMemorySnapshotStore:
    def __init__(self) -> None:
        self._snapshots: dict[tuple[str, int], dict] = {}

    def load(self, instance: str, board_id: int) -> dict[int, dict[str, Any]]:
        return self._snapshots.get((instance, board_id), {})

    def save(self, instance: str, board_id: int, snapshot: dict[int, dict[str, Any]]) -> None:
        self._snapshots[(instance, board_id)] = snapshot


class InMemoryExecutionLog:
    def __init__(self) -> None:
        self.results: list[ExecutionResult] = []

    def record(self, result: ExecutionResult) -> None:
        self.results.append(result)


class InMemoryActionRegistry:
    def __init__(self, actions: dict[str, Any]) -> None:
        self._actions = actions

    def get(self, name: str) -> Any:
        return self._actions[name]
