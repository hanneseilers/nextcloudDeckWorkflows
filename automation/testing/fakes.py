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

    def set_title(self, board_id: int, stack_id: int, card_id: int, title: str) -> None:
        self.calls.append(("set_title", board_id, stack_id, card_id, title))
        card = self._find_card(board_id, stack_id, card_id)
        if card is not None:
            card["title"] = title

    def set_description(self, board_id: int, stack_id: int, card_id: int, description: str) -> None:
        self.calls.append(("set_description", board_id, stack_id, card_id, description))
        card = self._find_card(board_id, stack_id, card_id)
        if card is not None:
            card["description"] = description

    def set_due_date(self, board_id: int, stack_id: int, card_id: int, due_date: Optional[str]) -> None:
        self.calls.append(("set_due_date", board_id, stack_id, card_id, due_date))
        card = self._find_card(board_id, stack_id, card_id)
        if card is not None:
            card["duedate"] = due_date

    def move_card(
        self, board_id: int, stack_id: int, card_id: int, target_stack_id: int, order: int = 0
    ) -> None:
        self.calls.append(("move_card", board_id, stack_id, card_id, target_stack_id, order))
        card = self._find_card(board_id, stack_id, card_id)
        if card is None:
            return
        for stack in self.list_stacks(board_id):
            if stack["id"] == stack_id:
                stack["cards"].remove(card)
            elif stack["id"] == target_stack_id:
                stack.setdefault("cards", []).append(card)

    def add_label(self, board_id: int, stack_id: int, card_id: int, label_id: int) -> None:
        self.calls.append(("add_label", board_id, stack_id, card_id, label_id))
        card = self._find_card(board_id, stack_id, card_id)
        if card is not None:
            card.setdefault("labels", []).append(label_id)

    def assign_user(self, board_id: int, stack_id: int, card_id: int, user_id: str) -> None:
        self.calls.append(("assign_user", board_id, stack_id, card_id, user_id))
        card = self._find_card(board_id, stack_id, card_id)
        if card is not None:
            card.setdefault("assignees", []).append(user_id)

    def unassign_user(self, board_id: int, stack_id: int, card_id: int, user_id: str) -> None:
        self.calls.append(("unassign_user", board_id, stack_id, card_id, user_id))
        card = self._find_card(board_id, stack_id, card_id)
        if card is not None and user_id in card.get("assignees", []):
            card["assignees"].remove(user_id)

    def add_comment(self, card_id: int, message: str) -> None:
        self.calls.append(("add_comment", card_id, message))

    def create_card(self, board_id: int, stack_id: int, title: str, description: str = "") -> dict[str, Any]:
        self.calls.append(("create_card", board_id, stack_id, title, description))
        existing_ids = [c["id"] for stacks in self.stacks.values() for st in stacks for c in st.get("cards", [])]
        card = {"id": max(existing_ids, default=0) + 1, "title": title, "description": description, "lastModified": 1}
        for stack in self.list_stacks(board_id):
            if stack["id"] == stack_id:
                stack.setdefault("cards", []).append(card)
                return dict(card)
        raise KeyError(f"no stack {stack_id} on board {board_id}")

    def _find_card(self, board_id: int, stack_id: int, card_id: int) -> Optional[dict[str, Any]]:
        for stack in self.list_stacks(board_id):
            if stack["id"] != stack_id:
                continue
            for card in stack.get("cards", []):
                if card["id"] == card_id:
                    return card
        return None


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

    def save_card(self, instance: str, board_id: int, card_id: int, state: Optional[dict[str, Any]]) -> None:
        board = self._snapshots.setdefault((instance, board_id), {})
        if state is None:
            board.pop(card_id, None)
        else:
            board[card_id] = state


class InMemoryExecutionLog:
    def __init__(self) -> None:
        self.results: list[ExecutionResult] = []

    def record(self, result: ExecutionResult) -> str:
        self.results.append(result)
        return f"fake-run-{len(self.results)}"


class InMemorySequenceStore:
    """Fake SequenceStorePort - a plain set per list_name."""

    def __init__(self) -> None:
        self._lists: dict[str, set[str]] = {}

    def contains_number(self, list_name: str, value: str) -> bool:
        return value in self._lists.get(list_name, set())

    def add_number(self, list_name: str, value: str) -> None:
        self._lists.setdefault(list_name, set()).add(value)

    def remove_number(self, list_name: str, value: str) -> None:
        self._lists.get(list_name, set()).discard(value)


class InMemoryActionRegistry:
    def __init__(self, actions: dict[str, Any]) -> None:
        self._actions = actions

    def get(self, name: str) -> Any:
        return self._actions[name]

    def list_names(self) -> list[str]:
        return sorted(self._actions)


class InMemoryActionLinkStore:
    """Fake ActionLinkStorePort - remembers what create_link was asked for."""

    def __init__(self) -> None:
        self.links: list[dict[str, Any]] = []

    def create_link(self, **kwargs: Any) -> str:
        self.links.append(kwargs)
        return f"token{len(self.links)}"


class InMemoryDuplicateGuard:
    """Fake DuplicateGuardPort - remembers keys forever (tests don't age them)."""

    def __init__(self) -> None:
        self.keys: set[str] = set()

    def seen_within(self, key: str, minutes: float) -> bool:
        return key in self.keys

    def remember(self, key: str) -> None:
        self.keys.add(key)
