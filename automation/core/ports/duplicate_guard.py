from __future__ import annotations

from typing import Protocol


class DuplicateGuardPort(Protocol):
    """Remembers that something was already done, for a limited time - used
    to keep an action with a visible side effect (send_email) from repeating
    when a killed run is repeated by the next one."""

    def seen_within(self, key: str, minutes: float) -> bool: ...

    def remember(self, key: str) -> None: ...
