from __future__ import annotations

from typing import Optional, Protocol


class CopyStorePort(Protocol):
    """Remembers which cards copy_card created, by which workflow and at which
    copy depth - so a workflow never reacts to its own copies, and a chain of
    copies of copies (a loop between workflows) is cut off."""

    def record_copy(self, instance: str, board_id: int, card_id: int, workflow_id: str, depth: int) -> None: ...

    def copy_info(self, instance: str, board_id: int, card_id: int) -> Optional[tuple[str, int]]:
        """(creating workflow id, copy depth) - or None for a card not made by copy_card."""
        ...
