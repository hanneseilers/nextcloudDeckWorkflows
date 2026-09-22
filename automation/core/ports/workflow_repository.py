from __future__ import annotations

from typing import Iterable, Optional, Protocol

from automation.core.domain.models import Workflow


class WorkflowRepositoryPort(Protocol):
    """Loads and persists workflow definitions."""

    def list_enabled(self) -> Iterable[Workflow]: ...

    def get(self, workflow_id: str) -> Optional[Workflow]: ...

    def save(self, workflow: Workflow) -> None: ...

    def delete(self, workflow_id: str) -> None: ...
