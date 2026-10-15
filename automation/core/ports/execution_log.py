from __future__ import annotations

from typing import Protocol

from automation.core.domain.models import ExecutionResult


class ExecutionLogPort(Protocol):
    """Records the outcome of a workflow run, for auditing and troubleshooting."""

    def record(self, result: ExecutionResult) -> str:
        """Returns the run id every recorded row of this run shares, so a
        caller (e.g. main.py's test-run processing) can link back to it."""
        ...
