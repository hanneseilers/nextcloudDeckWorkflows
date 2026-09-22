from __future__ import annotations

from typing import Protocol

from automation.core.domain.models import ExecutionResult


class ExecutionLogPort(Protocol):
    """Records the outcome of a workflow run, for auditing and troubleshooting."""

    def record(self, result: ExecutionResult) -> None: ...
