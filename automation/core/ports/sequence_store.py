from __future__ import annotations

from typing import Protocol


class SequenceStorePort(Protocol):
    """Tracks which values have already been handed out in a named sequence
    (used by generate_random_number/forget_random_number to avoid generating
    the same number twice). Multiple independent lists can coexist, keyed by
    `list_name`, so different workflows don't collide with each other."""

    def contains_number(self, list_name: str, value: str) -> bool: ...

    def add_number(self, list_name: str, value: str) -> None: ...

    def remove_number(self, list_name: str, value: str) -> None: ...
