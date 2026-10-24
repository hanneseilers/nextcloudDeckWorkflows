from __future__ import annotations

from typing import Any


class RecordingDeckGateway:
    """Wraps a DeckGatewayPort and notes every board an action writes to, as
    (instance, board_id) in a set shared across the run - so the fixed-point
    loop in main.py only polls again the boards that can have changed: those
    that had events, plus those an action wrote to (e.g. copy_card's target
    board). Read calls (list_*) and calls without a board (add_comment - its
    card's board had the event anyway) pass straight through."""

    def __init__(self, inner: Any, instance: str, written: set[tuple[str, int]]) -> None:
        self._inner = inner
        self._instance = instance
        self._written = written

    def __getattr__(self, name: str) -> Any:
        target = getattr(self._inner, name)
        if name.startswith("list_") or not callable(target):
            return target

        def recording(*args: Any, **kwargs: Any) -> Any:
            board_id = kwargs.get("board_id", args[0] if args and isinstance(args[0], int) else None)
            if board_id is not None:
                self._written.add((self._instance, int(board_id)))
            return target(*args, **kwargs)

        return recording
